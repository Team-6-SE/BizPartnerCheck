"""Asking all sources of a check run in parallel (S5.1).

execute_run() loads the run and its partner, asks every source of the run at the same
time and stores all answers with finish_run(). A source that has not answered when the
run's time limit is over gets an ERROR result ("did not answer in time"), so a run is
always complete or incomplete after at most CHECK_RUN_DEADLINE_SECONDS (default 30).

The Celery worker (app/checks/tasks.py) calls it for runs from the queue; without a
queue the API calls it itself after the response (app/checks/queue.py).
"""

import logging
import os
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters import bmf, firmenbuch, gisa, hfu, vies
from app.adapters.base import (
    NO_ANSWER_IN_TIME,
    CheckStatus,
    CheckSubject,
    SourceAdapter,
    SourceResult,
)
from app.checks.runs import RUNNING, finish_run, record_result
from app.db.models import CheckResult, CheckRun, Organization, Partner
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]

DEFAULT_DEADLINE_SECONDS = 30.0
# Sources that identify the partner by its VAT number only.
NEEDS_VAT_NUMBER = frozenset({vies.SOURCE, hfu.SOURCE})
# Sources that identify the partner by its company register number (FN) only.
NEEDS_REGISTER_NUMBER = frozenset({firmenbuch.SOURCE, gisa.SOURCE})
# BMF also compares the company name, so it waits for the name VIES returns in the
# same run (a new partner has no earlier VIES name).
WAITS_FOR = {bmf.SOURCE: vies.SOURCE}
# A waiting source is asked at the latest this long before the run's deadline.
WAIT_RESERVE_SECONDS = 5.0


def run_deadline() -> float:
    """CHECK_RUN_DEADLINE_SECONDS, or 30 s."""
    try:
        return float(os.environ.get("CHECK_RUN_DEADLINE_SECONDS", ""))
    except ValueError:
        return DEFAULT_DEADLINE_SECONDS


def default_adapters(sessions: SessionFactory) -> dict[str, SourceAdapter]:
    """The adapter of every source, as the worker builds them (no FastAPI request).

    The settings are the same as in the API (VIES_ADAPTER=fake-..., HFU_BASE_URL, ...).
    """
    # Imported here: the adapter modules import FastAPI dependencies.
    from app.adapters.bmf import BmfAdapter
    from app.adapters.fake import with_fake_from_env
    from app.adapters.firmenbuch import get_firmenbuch_adapter
    from app.adapters.gisa import get_gisa_adapter
    from app.adapters.hfu import get_hfu_adapter
    from app.adapters.vies import get_vies_adapter

    return {
        vies.SOURCE: get_vies_adapter(),
        bmf.SOURCE: with_fake_from_env(BmfAdapter(sessions)),
        hfu.SOURCE: get_hfu_adapter(),
        firmenbuch.SOURCE: get_firmenbuch_adapter(),
        gisa.SOURCE: get_gisa_adapter(),
    }


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
    """Ask every source of the run and store the results. Never raises.

    Every database step is a short transaction of its own: no connection is held while
    waiting for the sources, and each answer is visible as soon as it is stored.
    """
    try:
        with session_factory() as db:
            run = db.get(CheckRun, run_id)
            if run is None or run.status != RUNNING:
                return
            subject = _subject(db, run)
            sources = list(run.sources)
            db.commit()

        def store(result: SourceResult) -> None:
            with session_factory() as db:
                run = db.get(CheckRun, run_id)
                if run is not None:
                    record_result(db, run, result)

        results = ask_all(
            subject,
            [_adapter_or_none(adapters, source) for source in sources],
            sources,
            run_deadline() if deadline is None else deadline,
            on_result=store,
        )
        with session_factory() as db:
            run = db.get(CheckRun, run_id)
            if run is not None and run.status == RUNNING:
                finish_run(db, run, results)
    except ValueError as exc:
        # The run was closed meanwhile (e.g. as interrupted); its result stays.
        logger.info("check run %s not finished: %s", run_id, exc)
    except Exception:
        # The run stays "running"; crash safety (T5.1.5) marks it incomplete later.
        logger.exception("check run %s failed", run_id)


def ask_all(
    subject: CheckSubject,
    adapters: Sequence[SourceAdapter | None],
    sources: Sequence[str],
    deadline: float,
    *,
    on_result: Callable[[SourceResult], None] | None = None,
) -> list[SourceResult]:
    """Ask all sources at the same time; whoever is late or fails gets ERROR.

    on_result is called for every answer as soon as it is there (progress per source).
    A source in WAITS_FOR is asked after the source it waits for has answered (BMF
    needs the company name from VIES), at the latest WAIT_RESERVE_SECONDS before the
    deadline.
    """
    by_source = dict(zip(sources, adapters, strict=True))
    results: dict[str, SourceResult] = {}
    futures: dict[Future[SourceResult], str] = {}
    waiting: dict[str, str] = {}
    ends = time.monotonic() + deadline
    release_waiting_at = ends - min(WAIT_RESERVE_SECONDS, deadline / 2)
    pool = ThreadPoolExecutor(max_workers=max(len(sources), 1))

    def done(source: str, result: SourceResult) -> None:
        results[source] = result
        if on_result is not None:
            try:
                on_result(result)
            except Exception:
                logger.exception("storing the %s result failed", source)

    def submit(source: str, current: CheckSubject) -> None:
        adapter = by_source[source]
        assert adapter is not None
        futures[pool.submit(adapter.check, current)] = source

    def release(force: bool = False) -> None:
        for source, needed in list(waiting.items()):
            if force or needed in results:
                del waiting[source]
                submit(source, _with_registered_name(subject, results.get(needed)))

    try:
        for source in sources:
            adapter = by_source[source]
            if adapter is None:
                done(source, _error(source, "This source is not available."))
            elif source in NEEDS_VAT_NUMBER and not subject.vat_number:
                done(source, _not_applicable(source, "VAT number"))
            elif source in NEEDS_REGISTER_NUMBER and not subject.register_number:
                # E.g. a foreign partner: the Austrian register does not cover it.
                done(source, _not_applicable(source, "company register number"))
            elif WAITS_FOR.get(source) in by_source:
                waiting[source] = WAITS_FOR[source]
            else:
                submit(source, subject)
        release()

        while futures or waiting:
            now = time.monotonic()
            if now >= ends:
                break
            if waiting and now >= release_waiting_at:
                release(force=True)
            timeout = (release_waiting_at if waiting else ends) - now
            finished, _ = wait(
                futures, timeout=max(timeout, 0), return_when=FIRST_COMPLETED
            )
            for future in finished:
                source = futures.pop(future)
                try:
                    result = future.result()
                except Exception:
                    logger.exception("%s check failed", source)
                    result = _error(source, f"{source} could not be checked.")
                done(source, result)
            release()

        for source in sources:
            if source not in results:
                done(
                    source,
                    _error(
                        source,
                        f"{source} did not answer within {deadline:g} s. "
                        "The result was not confirmed.",
                        {"error": NO_ANSWER_IN_TIME, "deadline": deadline},
                    ),
                )
    finally:
        # Late sources keep running in their thread, but nobody waits for them.
        pool.shutdown(wait=False, cancel_futures=True)
    return [results[source] for source in sources]


def _with_registered_name(
    subject: CheckSubject, answer: SourceResult | None
) -> CheckSubject:
    """The subject with the name VIES has just returned (if it is valid and real)."""
    if (
        answer is None
        or answer.source != vies.SOURCE
        or answer.status != CheckStatus.OK
        or answer.raw.get("fake")
    ):
        return subject
    name = vies.company_name(answer.raw)
    return replace(subject, name=name) if name else subject


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
        # The latest real VIES name, else the name the user entered; a VIES answer in
        # this run replaces it before BMF is asked (WAITS_FOR).
        name=_registered_name(db, partner.id) or partner.company_name,
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


def _not_applicable(source: str, missing: str) -> SourceResult:
    name = "Firmenbuch" if source == firmenbuch.SOURCE else source
    return SourceResult(
        source=source,
        status=CheckStatus.NOT_APPLICABLE,
        explanation=f"No {missing}, {name} does not apply.",
        retrieved_at=datetime.now(UTC),
        data_as_of=None,
        raw={"notApplicable": f"no {missing}"},
    )
