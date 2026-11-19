"""Starting and finishing check runs (S5.1, T5.1.1).

A run is created as "running" with the list of sources it will ask. Each answer is
stored as soon as its source has answered (record_result, one short transaction), so
the progress screen sees the results one by one. finish_run() then stores ERROR for
the sources that were too late and sets the final status, under the same row lock,
so a run is never "complete" without its results.

    complete    every source of the run gave a result that is not ERROR
    incomplete  at least one source failed (ERROR) or gave no answer at all

Who asks the sources (the worker, T5.1.2) is not part of this module.

Crash safety (T5.1.5): a run that is still "running" long after it started belongs to
an API process or worker that stopped without finishing it. close_stale_runs() closes
such runs as incomplete, with an ERROR result for every source. It runs when the API
or a worker starts, and for a single run whenever its status is read.
"""

import logging
import os
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import CheckStatus, SourceResult
from app.db.models import CheckResult, CheckRun

logger = logging.getLogger(__name__)

RUNNING = "running"
COMPLETE = "complete"
INCOMPLETE = "incomplete"

# A run is asked within 30 s; a run still "running" after this long was interrupted.
# Generous, because a run may wait in the queue while all workers are busy.
DEFAULT_STALE_SECONDS = 120
INTERRUPTED = (
    "The check was interrupted before {source} answered. "
    "The result was not confirmed. Please check again."
)


def start_run(
    db: Session,
    *,
    organization_id: uuid.UUID,
    partner_id: uuid.UUID,
    sources: Iterable[str],
    started_by: str | None,
) -> CheckRun:
    """Create a running run. The caller commits (e.g. together with the queue job)."""
    names = list(dict.fromkeys(sources))  # keep the order, drop duplicates
    if not names:
        raise ValueError("A check run needs at least one source.")
    run = CheckRun(
        organization_id=organization_id,
        partner_id=partner_id,
        status=RUNNING,
        sources=names,
        started_by=started_by,
    )
    db.add(run)
    db.flush()
    return run


def final_status(sources: Iterable[str], results: Iterable[SourceResult]) -> str:
    """complete if every source has a result that is not ERROR, else incomplete."""
    return _status_of(sources, {r.source: r.status.value for r in results})


def _status_of(sources: Iterable[str], statuses: dict[str, str]) -> str:
    for source in sources:
        status = statuses.get(source)
        if status is None or status == CheckStatus.ERROR.value:
            return INCOMPLETE
    return COMPLETE


def _stored_statuses(db: Session, run_id: uuid.UUID) -> dict[str, str]:
    rows = db.execute(
        select(CheckResult.source, CheckResult.status).where(
            CheckResult.run_id == run_id
        )
    ).all()
    return {source: status for source, status in rows}


def _row(run: CheckRun, result: SourceResult) -> CheckResult:
    return CheckResult(
        partner_id=run.partner_id,
        run_id=run.id,
        source=result.source,
        status=result.status.value,
        checked_at=result.retrieved_at,
        raw_response=result.raw,
        explanation=result.explanation,
        data_as_of=result.data_as_of,
    )


def record_result(db: Session, run: CheckRun, result: SourceResult) -> bool:
    """Store one source's answer right away, so the progress screen can show it.

    Nothing is stored (False) if the run is no longer running (e.g. closed as
    interrupted), the source is not part of the run, or it already has a result.
    """
    try:
        db.refresh(run, with_for_update=True)
        if (
            run.status != RUNNING
            or result.source not in run.sources
            or result.source in _stored_statuses(db, run.id)
        ):
            db.rollback()
            return False
        db.add(_row(run, result))
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def finish_run(
    db: Session,
    run: CheckRun,
    results: Iterable[SourceResult],
    *,
    now: datetime | None = None,
) -> CheckRun:
    """Store the answers not stored yet and the run's final status in one transaction.

    Answers already stored by record_result are kept as they are; answers for sources
    that are not part of the run are ignored; sources without an answer make the run
    incomplete. A run that is already finished is not changed.
    """
    # Read the status again and lock the row: the run may have been closed as
    # interrupted (close_stale_runs) while its sources were being asked.
    db.refresh(run, with_for_update=True)
    if run.status != RUNNING:
        db.rollback()
        raise ValueError(f"Check run {run.id} is already {run.status}.")
    try:
        statuses = _stored_statuses(db, run.id)
        for result in results:
            if result.source in run.sources and result.source not in statuses:
                db.add(_row(run, result))
                statuses[result.source] = result.status.value
        run.status = _status_of(run.sources, statuses)
        run.finished_at = now or datetime.now(UTC)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return run


def stale_after() -> timedelta:
    """CHECK_RUN_STALE_SECONDS, or 120 s."""
    raw = os.environ.get("CHECK_RUN_STALE_SECONDS", "")
    try:
        seconds = float(raw) if raw.strip() else DEFAULT_STALE_SECONDS
    except ValueError:
        seconds = DEFAULT_STALE_SECONDS
    return timedelta(seconds=max(seconds, 1))


def is_stale(run: CheckRun, *, now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    return run.status == RUNNING and run.started_at < current - stale_after()


def _close_interrupted(db: Session, run: CheckRun, now: datetime) -> None:
    answered = _stored_statuses(db, run.id)
    for source in run.sources:
        if source in answered:
            continue
        db.add(
            CheckResult(
                partner_id=run.partner_id,
                run_id=run.id,
                source=source,
                status=CheckStatus.ERROR.value,
                checked_at=now,
                raw_response={"error": "RUN_INTERRUPTED"},
                explanation=INTERRUPTED.format(source=source),
            )
        )
    run.status = INCOMPLETE
    run.finished_at = now


def close_stale_runs(db: Session, *, now: datetime | None = None) -> int:
    """Close every interrupted run as incomplete. Returns how many were closed."""
    current = now or datetime.now(UTC)
    runs = db.scalars(
        select(CheckRun)
        .where(
            CheckRun.status == RUNNING,
            CheckRun.started_at < current - stale_after(),
        )
        # A worker finishing one of them at the same moment keeps its own result.
        .with_for_update(skip_locked=True)
    ).all()
    for run in runs:
        _close_interrupted(db, run, current)
    db.commit()
    if runs:
        logger.warning("Closed %d interrupted check run(s) as incomplete", len(runs))
    return len(runs)


def close_if_stale(db: Session, run: CheckRun, *, now: datetime | None = None) -> None:
    """Close this run as incomplete if it was interrupted (used when its status is read)."""
    current = now or datetime.now(UTC)
    if not is_stale(run, now=current):
        return
    db.refresh(run, with_for_update=True)
    if is_stale(run, now=current):
        _close_interrupted(db, run, current)
    db.commit()


def close_stale_runs_at_startup(session_factory) -> None:
    """Called when the API or a worker starts. Never stops the start."""
    if os.environ.get("CHECK_RUN_STARTUP_CLEANUP", "1") == "0":
        return
    try:
        with session_factory() as db:
            close_stale_runs(db)
    except Exception:
        logger.exception("Could not close interrupted check runs at startup")
