"""Deleting a partner: gone with its history, logged, isolated, not while a check runs."""

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CheckResult, CheckRun, Organization, Partner, SecurityEvent


def add_partner(client: TestClient, **fields: str) -> dict:
    response = client.post(
        "/api/v1/partners", json=fields or {"vat_number": "ATU12345678"}
    )
    assert response.status_code == 201
    return response.json()


def test_delete_removes_the_partner_and_its_whole_history(
    client: TestClient, db: Session
) -> None:
    partner = add_partner(client, vat_number="ATU12345678", company_name="Muster GmbH")
    client.post(f"/api/v1/partners/{partner['id']}/checks/vies")
    client.post(f"/api/v1/partners/{partner['id']}/checks/vies")
    partner_id = uuid.UUID(partner["id"])

    response = client.delete(f"/api/v1/partners/{partner['id']}")

    assert response.status_code == 204
    assert db.get(Partner, partner_id) is None
    assert (
        db.scalars(
            select(CheckResult).where(CheckResult.partner_id == partner_id)
        ).all()
        == []
    )
    assert client.get(f"/api/v1/partners/{partner['id']}").status_code == 404
    listed = {item["id"] for item in client.get("/api/v1/partners").json()["items"]}
    assert partner["id"] not in listed


def test_delete_is_written_to_the_security_log(client: TestClient, db: Session) -> None:
    partner = add_partner(client, vat_number="ATU12345678", company_name="Muster GmbH")
    client.post(f"/api/v1/partners/{partner['id']}/checks/vies")

    client.delete(f"/api/v1/partners/{partner['id']}")

    event = db.scalars(
        select(SecurityEvent).where(SecurityEvent.event_type == "PARTNER_DELETED")
    ).one()
    assert event.details["summary"] == "Partner Muster GmbH deleted with 1 check result"
    assert event.details["vat_number"] == "ATU12345678"
    assert event.details["check_results"] == 1
    assert event.actor_id is not None


def test_archived_partner_can_be_deleted(client: TestClient) -> None:
    partner = add_partner(client)
    client.patch(f"/api/v1/partners/{partner['id']}/archive")

    assert client.delete(f"/api/v1/partners/{partner['id']}").status_code == 204
    assert client.get("/api/v1/partners/archived").json() == []


def test_unknown_partner_gives_404(client: TestClient) -> None:
    response = client.delete(f"/api/v1/partners/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "partner_not_found"


def test_partner_of_another_organisation_is_not_deleted(
    client: TestClient, db: Session
) -> None:
    other = Organization(name="Other organization")
    db.add(other)
    db.flush()
    partner = Partner(organization_id=other.id, vat_number="DE123456789")
    db.add(partner)
    db.flush()

    response = client.delete(f"/api/v1/partners/{partner.id}")

    assert response.status_code == 404
    assert db.get(Partner, partner.id) is not None


def test_partner_with_a_running_check_is_not_deleted(
    client: TestClient, db: Session
) -> None:
    partner = add_partner(client)
    partner_id = uuid.UUID(partner["id"])
    stored = db.get(Partner, partner_id)
    assert stored is not None
    db.add(
        CheckRun(
            organization_id=stored.organization_id,
            partner_id=partner_id,
            status="running",
            sources=["VIES"],
            started_at=datetime.now(UTC),
        )
    )
    db.flush()

    response = client.delete(f"/api/v1/partners/{partner['id']}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "check_running"
    assert db.get(Partner, partner_id) is not None


def test_partner_with_finished_runs_is_deleted(client: TestClient, db: Session) -> None:
    partner = add_partner(client)
    started = client.post(f"/api/v1/partners/{partner['id']}/runs").json()
    assert client.get(f"/api/v1/runs/{started['id']}").json()["status"] != "running"

    assert client.delete(f"/api/v1/partners/{partner['id']}").status_code == 204
    assert db.get(CheckRun, uuid.UUID(started["id"])) is None
