"""API: GISA licence check per partner, in check runs and as latest result (S4.6).

GISA itself is replaced by FakeGisa (tests/conftest.py); reading and explaining its
answer is the real adapter code.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.base import CheckSubject, Scenario
from app.db.models import CheckResult, Organization, Partner


def add_partner(client: TestClient, **fields: str) -> dict:
    response = client.post(
        "/api/v1/partners", json=fields or {"company_register_number": "FN 123456a"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def run_check(client: TestClient, partner_id: str):
    return client.post(f"/api/v1/partners/{partner_id}/checks/gisa")


def test_active_licence_is_ok_and_every_licence_is_listed(
    client: TestClient, db: Session, fake_gisa
) -> None:
    partner = add_partner(client)

    response = run_check(client, partner["id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "GISA"
    assert body["status"] == "OK"
    assert fake_gisa.checked == ["123456a"]
    active, suspended = body["licences"]
    assert active == {
        "gisa_number": "12345678",
        "trade": "Baumeister (fake GISA)",
        "trade_key": "100",
        "state": "active",
        "start": "2018-04-01",
        "end": None,
        "suspended_since": None,
        "authority": "Magistrat der Stadt St. Pölten",
        "location": "Rathausplatz 6, 3100 St. Pölten",
        "manager_name": "Ing. Maria Muster",
        "manager_since": "2018-04-01",
    }
    assert suspended["state"] == "suspended"
    assert suspended["suspended_since"] == "2024-01-01"
    assert suspended["manager_name"] is None
    assert "1 active licence" in body["message"]

    stored = db.get(CheckResult, uuid.UUID(body["id"]))
    assert stored is not None and stored.status == "OK"


def test_no_active_licence_is_a_finding(client: TestClient, fake_gisa) -> None:
    partner = add_partner(client)
    fake_gisa.answer = fake_gisa.sample_answer(
        Scenario.FINDING, CheckSubject(vat_number=None, register_number="123456a")
    )

    body = run_check(client, partner["id"]).json()

    assert body["status"] == "FINDING"
    assert [lic["state"] for lic in body["licences"]] == ["ended", "suspended"]
    assert "no active licence" in body["message"]


def test_no_licence_and_unavailable_are_shown_differently(
    client: TestClient, fake_gisa
) -> None:
    partner = add_partner(client)
    fake_gisa.answer = {"checked": {"fnr": "123456a"}, "licences": []}
    none = run_check(client, partner["id"]).json()

    fake_gisa.answer = {"error": "NOT_REACHABLE", "message": "ConnectError"}
    unavailable = run_check(client, partner["id"]).json()

    assert none["status"] == "FINDING"
    assert none["licences"] == []
    assert unavailable["status"] == "ERROR"
    assert unavailable["licences"] is None
    assert "GISA could not be reached" in unavailable["message"]


def test_partner_without_register_number_cannot_be_checked(
    client: TestClient, db: Session, fake_gisa
) -> None:
    partner = add_partner(client, vat_number="DE123456789")

    response = run_check(client, partner["id"])

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_register_number"
    assert "so GISA cannot check it" in response.json()["detail"]["message"]
    assert fake_gisa.checked == []
    assert db.query(CheckResult).count() == 0


def test_partner_of_another_organisation_gives_404(
    client: TestClient, db: Session, fake_gisa
) -> None:
    other = Organization(name="Other organization")
    db.add(other)
    db.flush()
    partner = Partner(organization_id=other.id, company_register_number="123456a")
    db.add(partner)
    db.flush()

    response = run_check(client, str(partner.id))

    assert response.status_code == 404
    assert fake_gisa.checked == []


def test_list_shows_latest_gisa_result(client: TestClient, fake_gisa) -> None:
    checked = add_partner(client)
    add_partner(client, company_register_number="654321b")
    run_check(client, checked["id"])

    items = client.get("/api/v1/partners").json()["items"]

    by_number = {item["company_register_number"]: item for item in items}
    assert by_number["123456a"]["latest_gisa_check"]["status"] == "OK"
    assert by_number["654321b"]["latest_gisa_check"] is None


# --- check runs -------------------------------------------------------------------------


def test_runs_leave_gisa_out_until_it_is_set_up(client: TestClient) -> None:
    partner = add_partner(client)

    run = client.post(f"/api/v1/partners/{partner['id']}/runs").json()

    assert "GISA" not in run["sources"]


@pytest.fixture
def gisa_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GISA_API_KEY", "test-key")


@pytest.mark.usefixtures("gisa_enabled")
def test_run_asks_gisa_when_set_up(client: TestClient, fake_gisa) -> None:
    partner = add_partner(client)

    started = client.post(f"/api/v1/partners/{partner['id']}/runs").json()
    run = client.get(f"/api/v1/runs/{started['id']}").json()

    assert run["sources"] == ["VIES", "BMF", "HFU", "GISA"]
    result = next(r for r in run["results"] if r["source"] == "GISA")
    assert result["status"] == "OK"
    assert len(result["licences"]) == 2
    assert fake_gisa.checked == ["123456a"]


@pytest.mark.usefixtures("gisa_enabled")
def test_run_asks_firmenbuch_and_gisa_when_both_are_set_up(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FIRMENBUCH_ADAPTER", "fake-ok")
    partner = add_partner(client)

    run = client.post(f"/api/v1/partners/{partner['id']}/runs").json()

    assert run["sources"] == ["VIES", "BMF", "HFU", "FIRMENBUCH", "GISA"]


@pytest.mark.usefixtures("gisa_enabled")
def test_run_for_partner_without_register_number_is_not_applicable(
    client: TestClient, fake_gisa
) -> None:
    partner = add_partner(client, vat_number="DE123456789")

    started = client.post(f"/api/v1/partners/{partner['id']}/runs").json()
    run = client.get(f"/api/v1/runs/{started['id']}").json()

    result = next(r for r in run["results"] if r["source"] == "GISA")
    assert result["status"] == "NOT_APPLICABLE"
    assert result["message"] == "No company register number, GISA does not apply."
    assert fake_gisa.checked == []
