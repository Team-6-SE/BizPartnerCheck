"""Starting and finishing check runs (S5.1, T5.1.1).

A run is created as "running" with the list of sources it will ask. When the sources
have answered, finish_run() stores every answer as a check_results row of the run and
sets the final status in the same transaction, so a run is never "complete" without
its results and results never exist without their run.

    complete    every source of the run gave a result that is not ERROR
    incomplete  at least one source failed (ERROR) or gave no answer at all

Who asks the sources (the worker, T5.1.2) is not part of this module.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.base import CheckStatus, SourceResult
from app.db.models import CheckResult, CheckRun

RUNNING = "running"
COMPLETE = "complete"
INCOMPLETE = "incomplete"


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
    by_source = {result.source: result for result in results}
    for source in sources:
        result = by_source.get(source)
        if result is None or result.status == CheckStatus.ERROR:
            return INCOMPLETE
    return COMPLETE


def finish_run(
    db: Session,
    run: CheckRun,
    results: Iterable[SourceResult],
    *,
    now: datetime | None = None,
) -> CheckRun:
    """Store the answers of the run's sources and its final status in one transaction.

    Answers for sources that are not part of the run are ignored; sources without an
    answer make the run incomplete. A run that is already finished is not changed.
    """
    if run.status != RUNNING:
        raise ValueError(f"Check run {run.id} is already {run.status}.")
    wanted = set(run.sources)
    kept = [result for result in results if result.source in wanted]
    try:
        for result in kept:
            db.add(
                CheckResult(
                    partner_id=run.partner_id,
                    run_id=run.id,
                    source=result.source,
                    status=result.status.value,
                    checked_at=result.retrieved_at,
                    raw_response=result.raw,
                    explanation=result.explanation,
                    data_as_of=result.data_as_of,
                )
            )
        run.status = final_status(run.sources, kept)
        run.finished_at = now or datetime.now(UTC)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return run
