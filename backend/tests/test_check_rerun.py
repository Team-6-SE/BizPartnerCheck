"""Re-running a check (S5.3): a new run, the old one unchanged, changes highlighted."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CheckResult, CheckRun

INVALID = {"isValid": False, "userError": "INVALID", "name": "---", "address": "---"}


def add_partner(client: TestClient, vat_number: str = "ATU12345678") -> str:
    response = client.post("/api/v1/partners", json={"vat_number": vat_number})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def run_check(client: TestClient, partner_id: str) -> dict:
    started = client.post(f"/api/v1/partners/{partner_id}/runs")
    assert started.status_code == 202, started.text
    response = client.get(f"/api/v1/runs/{started.json()['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def snapshot(db: Session, run_id: str) -> list[tuple]:
    rows = db.scalars(
        select(CheckResult).where(CheckResult.run_id == uuid.UUID(run_id))
    ).all()
    return sorted(
        (str(r.id), r.source, r.status, r.checked_at, r.raw_response, r.explanation)
        for r in rows
    )


def test_a_re_run_creates_a_new_run_and_keeps_the_old_one(
    client: TestClient, db: Session
) -> None:
    partner_id = add_partner(client)
    first = run_check(client, partner_id)
    before = snapshot(db, first["id"])
    first_run = db.get(CheckRun, uuid.UUID(first["id"]))
    assert first_run is not None
    first_state = (first_run.status, first_run.started_at, first_run.finished_at)

    second = run_check(client, partner_id)

    assert second["id"] != first["id"]
    db.expire_all()
    assert snapshot(db, first["id"]) == before
    first_run = db.get(CheckRun, uuid.UUID(first["id"]))
    assert first_run is not None
    assert (first_run.status, first_run.started_at, first_run.finished_at) == (
        first_state
    )
    new_ids = {result["id"] for result in second["results"]}
    assert new_ids.isdisjoint({row[0] for row in before})


def test_the_first_run_has_nothing_to_compare(client: TestClient) -> None:
    run = run_check(client, add_partner(client))

    assert run["previous_run_id"] is None
    assert run["changes"] == []


def test_no_changes_when_every_source_says_the_same(client: TestClient) -> None:
    partner_id = add_partner(client)
    first = run_check(client, partner_id)

    second = run_check(client, partner_id)

    assert second["previous_run_id"] == first["id"]
    assert second["changes"] == []


def test_a_changed_status_is_reported(client: TestClient, fake_vies) -> None:
    partner_id = add_partner(client)
    run_check(client, partner_id)
    fake_vies.answer = INVALID

    second = run_check(client, partner_id)

    assert second["changes"] == [
        {"source": "VIES", "previous_status": "OK", "status": "FINDING"}
    ]


def test_compared_with_the_latest_finished_run_of_the_same_partner(
    client: TestClient, fake_vies
) -> None:
    partner_id = add_partner(client)
    other_id = add_partner(client, "ATU33864707")
    run_check(client, partner_id)
    fake_vies.answer = INVALID
    latest = run_check(client, partner_id)
    run_check(client, other_id)  # another partner: never compared

    third = run_check(client, partner_id)

    assert third["previous_run_id"] == latest["id"]
    assert third["changes"] == []


def test_a_running_run_has_no_comparison_yet(client: TestClient, db: Session) -> None:
    partner_id = add_partner(client)
    first = run_check(client, partner_id)
    organization_id = db.get(CheckRun, uuid.UUID(first["id"])).organization_id
    running = CheckRun(
        organization_id=organization_id,
        partner_id=uuid.UUID(partner_id),
        status="running",
        sources=["VIES"],
    )
    db.add(running)
    db.commit()

    body = client.get(f"/api/v1/runs/{running.id}").json()

    assert body["status"] == "running"
    assert body["previous_run_id"] is None
    assert body["changes"] == []
