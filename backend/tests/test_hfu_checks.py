"""API: HFU list check per partner and the latest result (fake ÖGK service), S4.4."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import CheckResult


def not_listed(answer: dict) -> dict:
    """The fake's answer with both HFU flags set to "N"."""
    entry = {**answer["auftragnehmerRS"][0], "hfuListeDgJN": "N", "hfuListeEpuJN": "N"}
    return {**answer, "auftragnehmerRS": [entry]}


def add_partner(client: TestClient, vat_number: str = "ATU12345678") -> dict:
    response = client.post("/api/v1/partners", json={"vat_number": vat_number})
    assert response.status_code == 201, response.text
    return response.json()


def run_check(client: TestClient, partner_id: str):
    return client.post(f"/api/v1/partners/{partner_id}/checks/hfu")


def set_organization_vat(client: TestClient, admin_token: str, vat_number: str) -> None:
    response = client.put(
        "/api/v1/organization",
        json={"vat_number": vat_number},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text


def test_listed_partner_is_ok_with_date(
    client: TestClient, db: Session, admin_token: str, fake_hfu
) -> None:
    set_organization_vat(client, admin_token, "ATU99999999")
    partner = add_partner(client)

    response = run_check(client, partner["id"])

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "OK"
    assert body["source"] == "HFU"
    assert "is on the HFU list as of 16 Nov 2026" in body["message"]
    assert "no withholding" in body["message"]
    assert body["data_as_of"] is None  # live source
    assert fake_hfu.checked == ["ATU12345678"]
    assert fake_hfu.requesters == ["ATU99999999"]

    stored = db.get(CheckResult, uuid.UUID(body["id"]))
    assert stored is not None
    assert stored.status == "OK"
    assert stored.explanation == body["message"]
    assert stored.raw_response["auftragnehmerRS"][0]["hfuListeDgJN"] == "J"
    assert stored.raw_response["stichtag"] == "2026-11-16"


def test_partner_not_on_the_list_is_finding_with_plain_words(
    client: TestClient, admin_token: str, fake_hfu
) -> None:
    set_organization_vat(client, admin_token, "ATU99999999")
    partner = add_partner(client)
    fake_hfu.answer = not_listed(fake_hfu.answer)

    body = run_check(client, partner["id"]).json()

    assert body["status"] == "FINDING"
    assert "is not on the HFU list as of 16 Nov 2026" in body["message"]
    assert "A withholding may apply to payments" in body["message"]


def test_without_organisation_vat_number_the_result_is_error(
    client: TestClient, db: Session, fake_hfu
) -> None:
    partner = add_partner(client)

    response = run_check(client, partner["id"])

    # Stored as a normal ERROR result: the partner was not confirmed.
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ERROR"
    assert "organisation's own VAT number is not set" in body["message"]
    assert fake_hfu.requesters == [None]
    stored = db.get(CheckResult, uuid.UUID(body["id"]))
    assert stored is not None and stored.raw_response["error"] == "NO_REQUESTER"


def test_service_error_is_stored_and_explained(
    client: TestClient, admin_token: str, fake_hfu
) -> None:
    set_organization_vat(client, admin_token, "ATU99999999")
    partner = add_partner(client)
    fake_hfu.answer = {"error": "NOT_REACHABLE", "message": "ConnectError"}

    body = run_check(client, partner["id"]).json()

    assert body["status"] == "ERROR"
    assert "could not be reached" in body["message"]
    assert "not confirmed" in body["message"]


def test_partner_without_vat_number_cannot_be_checked(
    client: TestClient, db: Session, fake_hfu
) -> None:
    response = client.post(
        "/api/v1/partners", json={"company_register_number": "123456a"}
    )
    partner = response.json()

    check = run_check(client, partner["id"])

    assert check.status_code == 409
    assert check.json()["detail"]["code"] == "no_vat_number"
    assert fake_hfu.checked == []
    assert db.query(CheckResult).count() == 0


def test_unknown_partner_gives_404(client: TestClient, fake_hfu) -> None:
    response = run_check(client, str(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "partner_not_found"
    assert fake_hfu.checked == []


def test_list_shows_latest_hfu_result(
    client: TestClient, admin_token: str, fake_hfu
) -> None:
    set_organization_vat(client, admin_token, "ATU99999999")
    checked = add_partner(client, "ATU11111111")
    not_checked = add_partner(client, "ATU22222222")

    listed = fake_hfu.answer
    fake_hfu.answer = not_listed(listed)
    run_check(client, checked["id"])
    fake_hfu.answer = listed
    latest = run_check(client, checked["id"]).json()

    partners = {p["vat_number"]: p for p in client.get("/api/v1/partners").json()}

    assert partners["ATU11111111"]["latest_hfu_check"] == latest
    assert partners["ATU11111111"]["latest_vies_check"] is None
    assert partners["ATU22222222"]["latest_hfu_check"] is None
    assert not_checked["latest_hfu_check"] is None
