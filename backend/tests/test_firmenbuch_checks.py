"""API: Firmenbuch check per partner, in check runs and as latest result (S4.5).

The Firmenbuch itself is replaced by FakeFirmenbuch (tests/conftest.py); reading and
explaining its answer is the real adapter code.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.bmf.importer import run_import
from app.db.models import CheckResult, Organization, Partner

SAMPLE = Path(__file__).parent / "fixtures" / "bmf_feed_sample.xml"


def add_partner(client: TestClient, **fields: str) -> dict:
    response = client.post(
        "/api/v1/partners", json=fields or {"company_register_number": "FN 123456a"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def run_check(client: TestClient, partner_id: str):
    return client.post(f"/api/v1/partners/{partner_id}/checks/firmenbuch")


def with_fact(answer: dict, text: str) -> dict:
    return {
        **answer,
        "legalFacts": [{"code": "99", "date": "2026-10-01", "text": text}],
    }


def import_bmf_list(db: Session) -> None:
    imported = datetime.now(UTC) - timedelta(hours=1)
    record = run_import(
        db, SAMPLE.read_bytes(), trigger="schedule", now=lambda: imported
    )
    assert record.status == "SUCCESS"


def test_registered_company_is_ok_with_details_and_persons(
    client: TestClient, db: Session, fake_firmenbuch
) -> None:
    partner = add_partner(client)

    response = run_check(client, partner["id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "FIRMENBUCH"
    assert body["status"] == "OK"
    assert fake_firmenbuch.checked == ["123456a"]
    assert body["company_name"] == "Muster Bau GmbH (fake Firmenbuch)"
    assert body["address"] == "Rathausplatz 6\n3100 St. Pölten"
    register = body["register_details"]
    assert register["found"] is True
    assert register["register_number"] == "123456a"
    assert register["legal_form"] == "Gesellschaft mit beschränkter Haftung"
    assert register["seat"] == "St. Pölten"
    assert register["flags"] == []
    assert register["persons"][0] == {
        "name": "Maria Muster",
        "role": "GESCHÄFTSFÜHRER/IN (handelsrechtlich)",
        "since": "2020-01-15",
    }
    assert "is registered in the Firmenbuch under FN 123456a" in body["message"]

    stored = db.get(CheckResult, uuid.UUID(body["id"]))
    assert stored is not None and stored.status == "OK"
    assert stored.explanation == body["message"]


def test_insolvency_is_a_finding_with_the_flag(
    client: TestClient, fake_firmenbuch
) -> None:
    partner = add_partner(client)
    fake_firmenbuch.answer = with_fact(fake_firmenbuch.answer, "Konkurs eröffnet")

    body = run_check(client, partner["id"]).json()

    assert body["status"] == "FINDING"
    assert body["register_details"]["flags"] == [
        {
            "kind": "insolvency",
            "label": "insolvency proceedings",
            "text": "Konkurs eröffnet",
            "date": "2026-10-01",
            "ended": False,
        }
    ]
    assert "Konkurs eröffnet" in body["message"]


def test_not_found_is_shown_differently_from_an_error(
    client: TestClient, fake_firmenbuch
) -> None:
    partner = add_partner(client)
    fake_firmenbuch.answer = {
        "stichtag": "2026-11-19",
        "checked": {"fnr": "123456a"},
        "notFound": True,
        "fault": "Firmenbuchnummer nicht gefunden",
    }
    not_found = run_check(client, partner["id"]).json()

    fake_firmenbuch.answer = {"error": "NOT_REACHABLE", "message": "ConnectError"}
    unavailable = run_check(client, partner["id"]).json()

    assert not_found["status"] == "FINDING"
    assert not_found["register_details"] == {
        "found": False,
        "register_number": "123456a",
        "legal_form": None,
        "seat": None,
        "flags": [],
        "persons": [],
    }
    assert "has no company with FN 123456a" in not_found["message"]
    assert unavailable["status"] == "ERROR"
    assert unavailable["register_details"] is None
    assert "could not be reached" in unavailable["message"]


def test_partner_without_register_number_cannot_be_checked(
    client: TestClient, db: Session, fake_firmenbuch
) -> None:
    partner = add_partner(client, vat_number="DE123456789")

    response = run_check(client, partner["id"])

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_register_number"
    assert fake_firmenbuch.checked == []
    assert db.query(CheckResult).count() == 0


def test_partner_of_another_organisation_gives_404(
    client: TestClient, db: Session, fake_firmenbuch
) -> None:
    other = Organization(name="Other organization")
    db.add(other)
    db.flush()
    partner = Partner(organization_id=other.id, company_register_number="123456a")
    db.add(partner)
    db.flush()

    response = run_check(client, str(partner.id))

    assert response.status_code == 404
    assert fake_firmenbuch.checked == []


def test_list_shows_latest_firmenbuch_result(
    client: TestClient, fake_firmenbuch
) -> None:
    checked = add_partner(client)
    add_partner(client, company_register_number="654321b")
    run_check(client, checked["id"])

    items = client.get("/api/v1/partners").json()["items"]

    by_number = {item["company_register_number"]: item for item in items}
    assert by_number["123456a"]["latest_firmenbuch_check"]["status"] == "OK"
    assert by_number["654321b"]["latest_firmenbuch_check"] is None


# --- check runs -------------------------------------------------------------------------


def test_runs_leave_the_firmenbuch_out_until_it_is_set_up(client: TestClient) -> None:
    partner = add_partner(client)

    run = client.post(f"/api/v1/partners/{partner['id']}/runs").json()

    assert "FIRMENBUCH" not in run["sources"]


@pytest.fixture
def firmenbuch_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRMENBUCH_API_KEY", "test-key")


@pytest.mark.usefixtures("firmenbuch_enabled")
def test_run_asks_the_firmenbuch_when_set_up(
    client: TestClient, db: Session, fake_firmenbuch
) -> None:
    import_bmf_list(db)
    partner = add_partner(client)

    started = client.post(f"/api/v1/partners/{partner['id']}/runs").json()
    run = client.get(f"/api/v1/runs/{started['id']}").json()

    assert run["sources"] == ["VIES", "BMF", "HFU", "FIRMENBUCH"]
    results = {r["source"]: r for r in run["results"]}
    assert results["FIRMENBUCH"]["status"] == "OK"
    assert results["FIRMENBUCH"]["register_details"]["seat"] == "St. Pölten"
    assert fake_firmenbuch.checked == ["123456a"]
    assert run["status"] == "complete"  # VIES and HFU: no VAT number, not applicable


@pytest.mark.usefixtures("firmenbuch_enabled")
def test_run_for_partner_without_register_number_is_not_applicable(
    client: TestClient, fake_firmenbuch
) -> None:
    partner = add_partner(client, vat_number="DE123456789")

    started = client.post(f"/api/v1/partners/{partner['id']}/runs").json()
    run = client.get(f"/api/v1/runs/{started['id']}").json()

    result = next(r for r in run["results"] if r["source"] == "FIRMENBUCH")
    assert result["status"] == "NOT_APPLICABLE"
    assert result["message"] == "No company register number, Firmenbuch does not apply."
    assert fake_firmenbuch.checked == []
