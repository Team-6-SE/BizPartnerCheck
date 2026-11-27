"""API for check runs (S5.1, T5.1.3).

    POST /api/v1/partners/{partner_id}/runs   start a run -> 202 with the run
    GET  /api/v1/runs/{run_id}                status and the results so far

The start returns at once; the sources are asked after the response, by the Celery
worker when CELERY_BROKER_URL is set, else in the API process (app/checks/queue.py).
Clients poll GET until the status is "complete" or "incomplete". Runs of other
organisations give 404.
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import bmf, firmenbuch, gisa, hfu, vies
from app.adapters.base import CheckStatus, SourceAdapter
from app.adapters.bmf import BmfAdapter
from app.adapters.fake import with_fake_from_env
from app.adapters.firmenbuch import get_firmenbuch_adapter
from app.adapters.gisa import get_gisa_adapter
from app.adapters.hfu import get_hfu_adapter
from app.adapters.vies import get_vies_adapter
from app.auth import AuthenticatedUser
from app.checks.executor import SessionFactory, get_session_factory
from app.checks.overall import DISCLAIMER, Level, overall_result
from app.checks.queue import RunDispatcher, get_run_dispatcher
from app.checks.runs import (
    RUNNING,
    close_if_stale,
    finish_run,
    is_stale,
    start_run,
)
from app.db.models import CheckResult, CheckRun, Partner
from app.db.session import get_db
from app.errors import api_error
from app.partners.router import CheckRead
from app.tenancy import get_current_organization_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["check runs"])

DbSession = Annotated[Session, Depends(get_db)]
OrganizationId = Annotated[uuid.UUID, Depends(get_current_organization_id)]
Sessions = Annotated[SessionFactory, Depends(get_session_factory)]
Dispatcher = Annotated[RunDispatcher, Depends(get_run_dispatcher)]

# The sources of every run, in the order the screen shows them.
RUN_SOURCES = (vies.SOURCE, bmf.SOURCE, hfu.SOURCE)


def run_sources() -> tuple[str, ...]:
    """RUN_SOURCES, and the Firmenbuch and GISA once they are set up (API key or fake).

    Without an API key every answer of these sources would be ERROR and every run
    incomplete, so they are left out until FIRMENBUCH_API_KEY / GISA_API_KEY is set.
    """
    optional = tuple(
        module.SOURCE for module in (firmenbuch, gisa) if module.is_enabled()
    )
    return (*RUN_SOURCES, *optional)


class RunChange(BaseModel):
    """A source whose status differs from the previous finished run (S5.3)."""

    source: str
    previous_status: CheckStatus
    status: CheckStatus


class ReasonRead(BaseModel):
    """What one source contributes to the overall result (S5.2)."""

    source: str
    # null: the source gave no result at all.
    status: CheckStatus | None
    level: Level


class OverallRead(BaseModel):
    """Overall traffic light of a finished run (S5.2, app/checks/overall.py)."""

    level: Level
    # Why, in one to three sentences.
    summary: str
    # Every source of the run with the level its result gives.
    reasons: list[ReasonRead]
    # The result is information only; the decision stays with the customer.
    disclaimer: str = DISCLAIMER

    @classmethod
    def from_run(
        cls, run: CheckRun, results: list[CheckResult]
    ) -> "OverallRead | None":
        if run.status == RUNNING:
            return None
        result = overall_result(run.sources, {r.source: r.status for r in results})
        return cls(
            level=result.level,
            summary=result.summary,
            reasons=[
                ReasonRead(source=r.source, status=r.status, level=r.level)
                for r in result.reasons
            ],
        )


class RunRead(BaseModel):
    id: uuid.UUID
    partner_id: uuid.UUID
    # running -> complete (every source answered) or incomplete (a source failed).
    status: str
    # Every source of the run; a source without a result is still "waiting".
    sources: list[str]
    started_at: datetime
    finished_at: datetime | None
    results: list[CheckRead]
    # GREEN, YELLOW or RED with the reasons (S5.2); null while the run is running.
    overall: OverallRead | None = None
    # The partner's previous finished run, if there is one (S5.3, re-run).
    previous_run_id: uuid.UUID | None = None
    # Sources whose status changed since that run; empty while running.
    changes: list[RunChange] = []

    @classmethod
    def from_run(
        cls,
        run: CheckRun,
        results: list[CheckResult],
        previous: tuple[CheckRun, list[CheckResult]] | None = None,
    ) -> "RunRead":
        order = {source: index for index, source in enumerate(run.sources)}
        ordered = sorted(results, key=lambda r: order.get(r.source, len(order)))
        return cls(
            id=run.id,
            partner_id=run.partner_id,
            status=run.status,
            sources=list(run.sources),
            started_at=run.started_at,
            finished_at=run.finished_at,
            results=[CheckRead.from_result(r) for r in ordered],
            overall=OverallRead.from_run(run, results),
            previous_run_id=previous[0].id if previous else None,
            changes=_changes(results, previous[1]) if previous else [],
        )


def _changes(
    results: list[CheckResult], previous: list[CheckResult]
) -> list[RunChange]:
    """Sources answered in both runs whose status is not the same."""
    before = {result.source: result.status for result in previous}
    return [
        RunChange(
            source=result.source,
            previous_status=CheckStatus(before[result.source]),
            status=CheckStatus(result.status),
        )
        for result in results
        if result.source in before and before[result.source] != result.status
    ]


def _running_run(db: Session, partner_id: uuid.UUID) -> CheckRun | None:
    """The partner's run that is still going on (an interrupted one is closed first)."""
    run = db.scalar(
        select(CheckRun)
        .where(CheckRun.partner_id == partner_id, CheckRun.status == RUNNING)
        .order_by(CheckRun.started_at.desc())
        .limit(1)
    )
    if run is None or not is_stale(run):
        return run
    close_if_stale(db, run)
    # close_if_stale ended the transaction: lock the partner again for the new run.
    db.scalar(select(Partner).where(Partner.id == partner_id).with_for_update())
    return None


def _results(db: Session, run: CheckRun) -> list[CheckResult]:
    return list(db.scalars(select(CheckResult).where(CheckResult.run_id == run.id)))


def _previous_run(
    db: Session, run: CheckRun
) -> tuple[CheckRun, list[CheckResult]] | None:
    """The partner's last finished run before this one, with its results."""
    previous = db.scalar(
        select(CheckRun)
        .where(
            CheckRun.partner_id == run.partner_id,
            CheckRun.id != run.id,
            CheckRun.status != RUNNING,
            CheckRun.started_at < run.started_at,
        )
        .order_by(CheckRun.started_at.desc())
        .limit(1)
    )
    return (previous, _results(db, previous)) if previous else None


def get_run_adapters(
    vies_adapter: Annotated[SourceAdapter, Depends(get_vies_adapter)],
    hfu_adapter: Annotated[SourceAdapter, Depends(get_hfu_adapter)],
    firmenbuch_adapter: Annotated[SourceAdapter, Depends(get_firmenbuch_adapter)],
    gisa_adapter: Annotated[SourceAdapter, Depends(get_gisa_adapter)],
    sessions: Sessions,
) -> dict[str, SourceAdapter]:
    """FastAPI dependency: one adapter per source of a run.

    The BMF adapter reads the list with its own sessions, because the run goes on
    after the request (and its session) has ended.
    """
    return {
        vies.SOURCE: vies_adapter,
        bmf.SOURCE: with_fake_from_env(BmfAdapter(sessions)),
        hfu.SOURCE: hfu_adapter,
        firmenbuch.SOURCE: firmenbuch_adapter,
        gisa.SOURCE: gisa_adapter,
    }


Adapters = Annotated[dict[str, SourceAdapter], Depends(get_run_adapters)]


@router.post(
    "/partners/{partner_id}/runs",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"description": "Partner not found"},
        409: {"description": "Partner is archived"},
        503: {"description": "The check queue is not reachable"},
    },
)
def start_check_run(
    partner_id: uuid.UUID,
    background: BackgroundTasks,
    db: DbSession,
    organization_id: OrganizationId,
    user: AuthenticatedUser,
    adapters: Adapters,
    sessions: Sessions,
    dispatch: Dispatcher,
) -> RunRead:
    """Start all checks of a partner at once and return the run immediately (202).

    Poll GET /runs/{id} for progress. Sources that need a VAT number give
    NOT_APPLICABLE for partners without one, the Firmenbuch and GISA for partners
    without a company register number; a source that fails or is too late
    gives ERROR and makes the run incomplete. While a run of the partner is still
    going on, the same run is returned instead of starting another one (so the
    sources are not flooded with requests).
    """
    partner = db.scalar(
        select(Partner)
        .where(Partner.id == partner_id, Partner.organization_id == organization_id)
        # Two clicks at the same moment: the second waits here, then finds the run.
        .with_for_update()
    )
    if partner is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            "partner_not_found",
            "This partner does not exist.",
        )
    if partner.is_archived:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "partner_archived",
            "This partner is archived. Restore it before checking it again.",
        )
    running = _running_run(db, partner.id)
    if running is not None:
        return RunRead.from_run(running, _results(db, running))
    run = start_run(
        db,
        organization_id=organization_id,
        partner_id=partner.id,
        sources=run_sources(),
        started_by=user.id,
    )
    db.commit()
    try:
        dispatch(run.id, background, adapters, sessions)
    except Exception:
        # E.g. Redis is down: the run can never finish, so close it as incomplete.
        logger.exception("check run %s could not be queued", run.id)
        finish_run(db, run, [])
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "check_queue_unavailable",
            "Checks cannot start right now. Please try again in a moment.",
        ) from None
    return RunRead.from_run(run, [])


@router.get(
    "/runs/{run_id}",
    response_model=RunRead,
    responses={404: {"description": "Run not found"}},
)
def get_check_run(
    run_id: uuid.UUID, db: DbSession, organization_id: OrganizationId
) -> RunRead:
    """Status of a run and the results stored so far."""
    run = db.scalar(
        select(CheckRun).where(
            CheckRun.id == run_id, CheckRun.organization_id == organization_id
        )
    )
    if run is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "run_not_found", "This check run does not exist."
        )
    # A run interrupted by a crash would otherwise stay "running" forever (T5.1.5).
    close_if_stale(db, run)
    if run.status == RUNNING:
        return RunRead.from_run(run, _results(db, run))
    return RunRead.from_run(run, _results(db, run), _previous_run(db, run))
