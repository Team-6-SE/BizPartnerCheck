"""Performance of check runs (S5.1, T5.1.6).

20 runs are started at the same time and executed by PERF_WORKERS parallel workers
(default 4, like `celery worker --concurrency=4`). Every source is a stub that answers
after 2 s. Done when 95 % of the runs are finished within 15 s, counted from the moment
all 20 were started (so the time a run waits for a free worker counts too).

Slow (about 10 s) and it writes to the database, so it only runs on request:

    RUN_PERFORMANCE_TESTS=1 uv run pytest tests/test_check_run_performance.py -s

(PowerShell: $env:RUN_PERFORMANCE_TESTS="1"; uv run pytest tests/test_check_run_performance.py -s)
"""

import math
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.adapters.base import CheckStatus, CheckSubject, SourceAdapter, SourceResult
from app.checks.executor import execute_run
from app.checks.runs import COMPLETE, start_run
from app.db.models import CheckResult, CheckRun, Organization, Partner
from app.db.session import SessionLocal

slow = pytest.mark.skipif(
    not os.environ.get("RUN_PERFORMANCE_TESTS"),
    reason="slow; set RUN_PERFORMANCE_TESTS=1 to run it",
)

RUNS = 20
WORKERS = int(os.environ.get("PERF_WORKERS", "4"))
SOURCE_DELAY_SECONDS = 2.0
LIMIT_SECONDS = 15.0
SHARE = 0.95
SOURCES = ("VIES", "BMF", "HFU")


class StubSource(SourceAdapter):
    """A source that always answers OK after 2 s, without network."""

    def __init__(self, source: str) -> None:
        self.source = source  # read by the base class for its time limits
        super().__init__()

    def check(self, subject: CheckSubject) -> SourceResult:
        time.sleep(SOURCE_DELAY_SECONDS)
        return SourceResult(
            self.source, CheckStatus.OK, "stub", datetime.now(UTC), None, {"stub": 1}
        )

    def query(self, subject, timeout):  # pragma: no cover - not used
        return {}

    def interpret(self, raw):  # pragma: no cover - not used
        raise NotImplementedError

    def describe(self, status, raw):  # pragma: no cover - not used
        return ""

    def sample_answer(self, scenario, subject):  # pragma: no cover - not used
        return {}


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[max(math.ceil(share * len(ordered)) - 1, 0)]


@slow
def test_95_percent_of_20_parallel_runs_finish_within_15_seconds() -> None:
    adapters = {source: StubSource(source) for source in SOURCES}
    with SessionLocal() as db:
        organization = Organization(name=f"Performance test {uuid.uuid4()}")
        db.add(organization)
        db.flush()
        partner = Partner(organization_id=organization.id, vat_number="ATU12345678")
        db.add(partner)
        db.flush()
        run_ids = [
            start_run(
                db,
                organization_id=organization.id,
                partner_id=partner.id,
                sources=SOURCES,
                started_by="performance-test",
            ).id
            for _ in range(RUNS)
        ]
        db.commit()
        organization_id, partner_id = organization.id, partner.id

    try:
        started = time.monotonic()

        def finish(run_id: uuid.UUID) -> float:
            execute_run(run_id, adapters, SessionLocal)
            return time.monotonic() - started

        with ThreadPoolExecutor(max_workers=WORKERS) as workers:
            durations = list(workers.map(finish, run_ids))

        with SessionLocal() as db:
            statuses = db.scalars(
                select(CheckRun.status).where(CheckRun.id.in_(run_ids))
            ).all()
        p95 = percentile(durations, SHARE)
        print(
            f"\n{RUNS} runs, {WORKERS} workers, sources answer after "
            f"{SOURCE_DELAY_SECONDS:g} s: fastest {min(durations):.1f} s, "
            f"95 % within {p95:.1f} s, slowest {max(durations):.1f} s"
        )

        assert list(statuses).count(COMPLETE) == RUNS
        assert p95 <= LIMIT_SECONDS
    finally:
        with SessionLocal() as db:
            db.execute(delete(CheckResult).where(CheckResult.partner_id == partner_id))
            db.execute(delete(CheckRun).where(CheckRun.partner_id == partner_id))
            db.execute(delete(Partner).where(Partner.id == partner_id))
            db.execute(delete(Organization).where(Organization.id == organization_id))
            db.commit()


def test_percentile() -> None:
    values = [float(n) for n in range(1, 21)]

    assert percentile(values, 0.95) == 19.0
    assert percentile(values, 1.0) == 20.0
    assert percentile([3.0], 0.95) == 3.0
