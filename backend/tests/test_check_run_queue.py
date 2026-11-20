"""Check runs through the Celery queue (S5.1, T5.1.2). No Redis needed."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.checks import queue, tasks
from app.checks.queue import enqueue_run, get_run_dispatcher, run_in_background
from app.db.models import CheckRun
from app.db.session import SessionLocal
from app.main import app
from app.worker import celery_app


def test_without_broker_the_api_runs_checks_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)

    assert get_run_dispatcher() is run_in_background


def test_with_broker_runs_go_to_the_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

    assert get_run_dispatcher() is enqueue_run


def test_only_the_run_id_is_sent_to_the_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(
        tasks.run_check, "apply_async", lambda **kwargs: sent.append(kwargs)
    )
    run_id = uuid.uuid4()

    enqueue_run(run_id, None, {}, SessionLocal)  # type: ignore[arg-type]

    assert sent == [{"args": [str(run_id)], "retry": False}]


def test_the_task_is_registered_under_its_name() -> None:
    assert tasks.TASK_NAME in celery_app.tasks


def test_the_task_executes_the_run_with_all_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(tasks, "execute_run", lambda *args: calls.append(args))
    run_id = uuid.uuid4()

    tasks.run_check.run(str(run_id))

    ((called_id, adapters, sessions),) = calls
    assert called_id == run_id
    # Every source has an adapter; the run's own source list decides who is asked.
    assert set(adapters) == {"VIES", "BMF", "HFU", "FIRMENBUCH", "GISA"}
    assert sessions is SessionLocal


def test_queue_down_gives_503_and_an_incomplete_run(
    client: TestClient, db: Session
) -> None:
    def broken(*_args) -> None:
        raise ConnectionError("Redis is not reachable")

    app.dependency_overrides[get_run_dispatcher] = lambda: broken
    partner = client.post("/api/v1/partners", json={"vat_number": "ATU12345678"})
    assert partner.status_code == 201, partner.text

    response = client.post(f"/api/v1/partners/{partner.json()['id']}/runs")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "check_queue_unavailable"
    run = db.query(CheckRun).one()
    assert run.status == "incomplete"
    assert run.finished_at is not None


def test_queue_module_reads_the_setting_each_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CELERY_BROKER_URL", "")
    assert not queue.queue_enabled()
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    assert queue.queue_enabled()
