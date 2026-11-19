"""Crash safety of check runs (S5.1, T5.1.5): interrupted runs become incomplete."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import CheckStatus, SourceResult
from app.checks import runs as runs_module
from app.checks import tasks
from app.checks.runs import (
    COMPLETE,
    INCOMPLETE,
    RUNNING,
    close_stale_runs,
    close_stale_runs_at_startup,
    finish_run,
    stale_after,
)
from app.db.models import CheckResult, CheckRun, Organization, Partner
from app.db.session import SessionLocal

SOURCES = ["VIES", "BMF", "HFU"]


def make_run(
    db: Session,
    *,
    minutes_ago: float,
    status: str = RUNNING,
    partner: Partner | None = None,
) -> CheckRun:
    if partner is None:
        organization = Organization(name="Crash test organisation")
        db.add(organization)
        db.flush()
        partner = Partner(organization_id=organization.id, vat_number="ATU12345678")
        db.add(partner)
        db.flush()
    run = CheckRun(
        organization_id=partner.organization_id,
        partner_id=partner.id,
        status=status,
        sources=SOURCES,
        started_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    db.add(run)
    db.commit()
    return run


def results_of(db: Session, run: CheckRun) -> list[CheckResult]:
    return list(db.scalars(select(CheckResult).where(CheckResult.run_id == run.id)))


def test_an_interrupted_run_is_closed_with_an_error_per_source(db: Session) -> None:
    run = make_run(db, minutes_ago=10)

    closed = close_stale_runs(db)

    assert closed == 1
    db.refresh(run)
    assert run.status == INCOMPLETE
    assert run.finished_at is not None
    results = results_of(db, run)
    assert sorted(r.source for r in results) == sorted(SOURCES)
    assert all(r.status == "ERROR" for r in results)
    assert all("interrupted" in (r.explanation or "") for r in results)


def test_a_run_that_just_started_is_left_alone(db: Session) -> None:
    run = make_run(db, minutes_ago=0)

    assert close_stale_runs(db) == 0

    db.refresh(run)
    assert run.status == RUNNING
    assert results_of(db, run) == []


def test_finished_runs_are_left_alone(db: Session) -> None:
    run = make_run(db, minutes_ago=10, status=COMPLETE)

    assert close_stale_runs(db) == 0

    db.refresh(run)
    assert run.status == COMPLETE


def test_a_worker_cannot_finish_a_run_that_was_closed(db: Session) -> None:
    run = make_run(db, minutes_ago=10)
    close_stale_runs(db)
    late = SourceResult("VIES", CheckStatus.OK, "", datetime.now(UTC), None, {})

    with pytest.raises(ValueError):
        finish_run(db, run, [late])

    assert run.status == INCOMPLETE
    assert len(results_of(db, run)) == len(SOURCES)


def test_reading_an_interrupted_run_closes_it(client: TestClient, db: Session) -> None:
    created = client.post("/api/v1/partners", json={"vat_number": "ATU12345678"})
    assert created.status_code == 201, created.text
    partner = db.get(Partner, uuid.UUID(created.json()["id"]))
    run = make_run(db, minutes_ago=10, partner=partner)

    response = client.get(f"/api/v1/runs/{run.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == INCOMPLETE
    assert {r["status"] for r in body["results"]} == {"ERROR"}
    assert len(body["results"]) == len(SOURCES)


def test_reading_a_recent_run_keeps_it_running(client: TestClient, db: Session) -> None:
    created = client.post("/api/v1/partners", json={"vat_number": "ATU12345678"})
    partner = db.get(Partner, uuid.UUID(created.json()["id"]))
    run = make_run(db, minutes_ago=0, partner=partner)

    body = client.get(f"/api/v1/runs/{run.id}").json()

    assert body["status"] == RUNNING
    assert body["results"] == []


def test_startup_cleanup_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECK_RUN_STARTUP_CLEANUP", "0")
    used: list[bool] = []

    close_stale_runs_at_startup(lambda: used.append(True))

    assert used == []


def test_startup_cleanup_never_stops_the_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECK_RUN_STARTUP_CLEANUP", "1")

    def broken():
        raise ConnectionError("database down")

    close_stale_runs_at_startup(broken)  # no exception


def test_a_starting_worker_closes_interrupted_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(tasks, "close_stale_runs_at_startup", calls.append)

    tasks.close_interrupted_runs(sender=None)

    assert calls == [SessionLocal]


@pytest.mark.parametrize(
    ("value", "seconds"), [("", 120), ("300", 300), ("abc", 120), ("0", 1)]
)
def test_stale_time_from_environment(
    monkeypatch: pytest.MonkeyPatch, value: str, seconds: int
) -> None:
    monkeypatch.setenv("CHECK_RUN_STALE_SECONDS", value)

    assert stale_after() == timedelta(seconds=seconds)
    assert runs_module.DEFAULT_STALE_SECONDS == 120
