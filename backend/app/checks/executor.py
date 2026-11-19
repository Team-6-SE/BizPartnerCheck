"""Asking all sources of a check run in parallel (S5.1).

execute_run() loads the run and its partner, asks every source of the run at the same
time and stores all answers with finish_run(). A source that has not answered when the
run's time limit is over gets an ERROR result ("did not answer in time"), so a run is
always complete or incomplete after at most CHECK_RUN_DEADLINE_SECONDS (default 30).

For now the web app starts it as a FastAPI background task; the Celery worker (T5.1.2)
will call the same function.
"""

import logging
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import AbstractContextManager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import hfu, vies
from app.adapters.base import (
    NO_ANSWER_IN_TIME,
    CheckStatus,
    CheckSubject,
    SourceAdapter,
    SourceResult,
)
from app.checks.runs import RUNNING, finish_run
from app.db.models import CheckResult, CheckRun, Organization, Partner
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]

DEFAULT_DEADLINE_SECONDS = 30.0
# Sources that identify the partner by its VAT number only.
NEEDS_VAT_NUMBER = frozenset({vies.SOURCE, hfu.SOURCE})


def run_deadline() -> float:
    """CHECK_RUN_DEADLINE_SECONDS, or 30 s."""
    try:
        return float(os.environ.get("CHECK_RUN_DEADLINE_SECONDS", ""))
    except ValueError:
        return DEFAULT_DEADLINE_SECONDS


def get_session_factory() -> SessionFactory:
    """FastAPI dependency: new database sessions for work after the response."""
    return SessionLocal


def execute_run(
    run_id: uuid.UUID,
    adapters: Mapping[str, SourceAdapter],
    session_factory: SessionFactory,
    *,
    deadline: float | None = None,
) -> None:
    """Ask every source of the run and store the results. Never raises."""
    try:
        with session_factory() as db:
            run = db.get(CheckRun, run_id)
            if run is None or run.status != RUNNING:
                return
            subject = _subject(db, run)
            # No database connection is held while waiting for the sources.
            db.commit()
            results = ask_all(
                subject,
                [_adapter_or_none(adapters, source) for source in run.sources],
                run.sources,
                run_deadline() if deadline is None else deadline,
            )
            finish_run(db, run, results)
    except Exception:
        # The run stays "running"; crash safety (T5.1.5) marks it incomplete later.
        logger.exception("check run %s failed", run_id)


def ask_all(
    subject: CheckSubject,
    adapters: Sequence[SourceAdapter | None],
    sources: Sequence[str],
    deadline: float,
) -> list[SourceResult]:
    """Ask all sources at the same time; whoever is late or fails gets ERROR."""
    results: dict[str, SourceResult] = {}
    futures: dict[Future[SourceResult], str] = {}
    pool = ThreadPoolExecutor(max_workers=max(len(sources), 1))
    try:
        for source, adapter in zip(sources, adapters, strict=True):
            if adapter is None:
                results[source] = _error(source, "This source is not available.")
            elif source in NEEDS_VAT_NUMBER and not subject.vat_number:
                results[source] = _not_applicable(source)
            else:
                futures[pool.submit(adapter.check, subject)] = source
        done, _late = wait(futures, timeout=deadline)
        for future, source in futures.items():
            if future not in done:
                results[source] = _error(
                    source,
                    f"{source} did not answer within {deadline:g} s. "
                    "The result was not confirmed.",
                    {"error": NO_ANSWER_IN_TIME, "deadline": deadline},
                )
                continue
            try:
                results[source] = future.result()
            except Exception:
                logger.exception("%s check failed", source)
                results[source] = _error(source, f"{source} could not be checked.")
    finally:
        # Late sources keep running in their thread, but nobody waits for them.
        pool.shutdown(wait=False, cancel_futures=True)
    return [results[source] for source in sources if source in results]


def _adapter_or_none(
    adapters: Mapping[str, SourceAdapter], source: str
) -> SourceAdapter | None:
    return adapters.get(source)


def _subject(db: Session, run: CheckRun) -> CheckSubject:
    partner = db.get(Partner, run.partner_id)
    if partner is None:
        raise LookupError(f"partner {run.partner_id} of run {run.id} is missing")
    requester_vat = db.scalar(
        select(Organization.vat_number).where(Organization.id == run.organization_id)
    )
    return CheckSubject(
        vat_number=partner.vat_number,
        register_number=partner.company_register_number,
        name=_registered_name(db, partner.id),
        requester_vat=requester_vat,
    )


def _registered_name(db: Session, partner_id: uuid.UUID) -> str | None:
    """The registered name from the latest valid VIES check (for the BMF name match)."""
    result = db.scalar(
        select(CheckResult)
        .where(
            CheckResult.partner_id == partner_id,
            CheckResult.source == vies.SOURCE,
            CheckResult.status == CheckStatus.OK.value,
        )
        .order_by(CheckResult.checked_at.desc(), CheckResult.id.desc())
        .limit(1)
    )
    # Fake VIES names must never be used for a real comparison.
    if result is None or result.raw_response.get("fake"):
        return None
    return vies.company_name(result.raw_response)


def _error(source: str, explanation: str, raw: dict | None = None) -> SourceResult:
    return SourceResult(
        source=source,
        status=CheckStatus.ERROR,
        explanation=explanation,
        retrieved_at=datetime.now(UTC),
        data_as_of=None,
        raw=raw or {"error": "RUN_FAILED"},
    )


def _not_applicable(source: str) -> SourceResult:
    return SourceResult(
        source=source,
        status=CheckStatus.NOT_APPLICABLE,
        explanation=f"No VAT number, {source} does not apply.",
        retrieved_at=datetime.now(UTC),
        data_as_of=None,
        raw={"notApplicable": "no VAT number"},
    )
