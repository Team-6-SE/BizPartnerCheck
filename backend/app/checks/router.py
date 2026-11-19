"""API for check runs (S5.1, T5.1.3).

    POST /api/v1/partners/{partner_id}/runs   start a run -> 202 with the run
    GET  /api/v1/runs/{run_id}                status and the results so far

The start returns at once; the sources are asked after the response (for now as a
FastAPI background task, later by the Celery worker). Clients poll GET until the
status is "complete" or "incomplete". Runs of other organisations give 404.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import bmf, hfu, vies
from app.adapters.base import SourceAdapter
from app.adapters.bmf import BmfAdapter
from app.adapters.fake import with_fake_from_env
from app.adapters.hfu import get_hfu_adapter
from app.adapters.vies import get_vies_adapter
from app.auth import AuthenticatedUser
from app.checks.executor import SessionFactory, execute_run, get_session_factory
from app.checks.runs import start_run
from app.db.models import CheckResult, CheckRun, Partner
from app.db.session import get_db
from app.errors import api_error
from app.partners.router import CheckRead
from app.tenancy import get_current_organization_id

router = APIRouter(tags=["check runs"])

DbSession = Annotated[Session, Depends(get_db)]
OrganizationId = Annotated[uuid.UUID, Depends(get_current_organization_id)]
Sessions = Annotated[SessionFactory, Depends(get_session_factory)]

# The sources of every run, in the order the screen shows them.
RUN_SOURCES = (vies.SOURCE, bmf.SOURCE, hfu.SOURCE)


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

    @classmethod
    def from_run(cls, run: CheckRun, results: list[CheckResult]) -> "RunRead":
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
        )


def get_run_adapters(
    vies_adapter: Annotated[SourceAdapter, Depends(get_vies_adapter)],
    hfu_adapter: Annotated[SourceAdapter, Depends(get_hfu_adapter)],
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
    }


Adapters = Annotated[dict[str, SourceAdapter], Depends(get_run_adapters)]


@router.post(
    "/partners/{partner_id}/runs",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"description": "Partner not found"},
        409: {"description": "Partner is archived"},
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
) -> RunRead:
    """Start all checks of a partner at once and return the run immediately (202).

    Poll GET /runs/{id} for progress. Sources that need a VAT number give
    NOT_APPLICABLE for partners without one; a source that fails or is too late
    gives ERROR and makes the run incomplete.
    """
    partner = db.scalar(
        select(Partner).where(
            Partner.id == partner_id, Partner.organization_id == organization_id
        )
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
    run = start_run(
        db,
        organization_id=organization_id,
        partner_id=partner.id,
        sources=RUN_SOURCES,
        started_by=user.id,
    )
    db.commit()
    background.add_task(execute_run, run.id, adapters, sessions)
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
    results = list(db.scalars(select(CheckResult).where(CheckResult.run_id == run.id)))
    return RunRead.from_run(run, results)
