"""API: run a VIES check for a partner and show the latest result (fake VIES)."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CheckResult, Organization, Partner

INVALID_ANSWER = {"isValid": False, "userError": "INVALID", "name": "---"}
# VIES refused the organisation's own VAT number (the requester).
REQUESTER_REJECTED = {
    "isValid": False,
    "userError": "INVALID_REQUESTER_INFO",
    "name": "---",
    "address": "---",
}


def add_partner(client: TestClient, vat_number: str = "ATU12345678") -> dict:
    response = client.post("/api/v1/partners", json={"vat_number": vat_number})
    assert response.status_code == 201
    return response.json()


def run_check(client: TestClient, partner_id: str):
    return client.post(f"/api/v1/partners/{partner_id}/checks/vies")


def set_organization_vat(client: TestClient, admin_token: str, vat_number: str) -> None:
    response = client.put(
        "/api/v1/organization",
        json={"vat_number": vat_number},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200


def test_new_partner_has_no_check_yet(client: TestClient) -> None:
    partner = add_partner(client)

    assert partner["latest_vies_check"] is None
    assert (
        client.get("/api/v1/partners").json()["items"][0]["latest_vies_check"] is None
    )


def test_valid_result_is_returned_and_stored(
    client: TestClient, db: Session, fake_vies
) -> None:
    partner = add_partner(client)

    response = run_check(client, partner["id"])

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "OK"
    assert body["source"] == "VIES"
    assert body["company_name"] == "Muster Bau GmbH"
    assert body["message"]
    assert fake_vies.checked == ["ATU12345678"]

    stored = db.get(CheckResult, uuid.UUID(body["id"]))
    assert stored is not None
    assert stored.partner_id == uuid.UUID(partner["id"])
    assert stored.status == "OK"
    assert stored.raw_response["userError"] == "VALID"
    # The explanation shown now is kept as evidence; VIES is live, so no data age.
    assert stored.explanation == body["message"]
    assert stored.data_as_of is None
    assert body["data_as_of"] is None
    # Stored with the time of the check.
    assert abs(stored.checked_at - datetime.now(UTC)) < timedelta(minutes=1)


def test_valid_result_contains_the_registered_address(
    client: TestClient, fake_vies
) -> None:
    partner = add_partner(client)

    body = run_check(client, partner["id"]).json()

    assert body["address"] == "Hauptstrasse 1\nAT-1010 Wien"
    # Without an organisation VAT number VIES is asked without a requester and
    # gives no consultation number.
    assert body["consultation_number"] is None
    assert fake_vies.requesters == [None]


def test_consultation_number_with_organization_vat_number(
    client: TestClient, db: Session, admin_token: str, fake_vies
) -> None:
    set_organization_vat(client, admin_token, "ATU99999999")
    partner = add_partner(client)
    # With a requester, VIES adds the consultation number to the valid answer.
    fake_vies.answer = {**fake_vies.answer, "requestIdentifier": "WAPIAAAAZ1B2C3D4"}

    body = run_check(client, partner["id"]).json()

    assert body["status"] == "OK"
    assert body["address"] == "Hauptstrasse 1\nAT-1010 Wien"
    assert body["consultation_number"] == "WAPIAAAAZ1B2C3D4"
    assert fake_vies.requesters == ["ATU99999999"]
    # Kept as evidence and shown again in the partner list.
    stored = db.get(CheckResult, uuid.UUID(body["id"]))
    assert stored.raw_response["requestIdentifier"] == "WAPIAAAAZ1B2C3D4"
    listed = client.get("/api/v1/partners").json()["items"][0]["latest_vies_check"]
    assert listed["consultation_number"] == "WAPIAAAAZ1B2C3D4"
    assert listed["address"] == "Hauptstrasse 1\nAT-1010 Wien"


def test_rejected_organization_vat_number_is_explained(
    client: TestClient, admin_token: str, fake_vies
) -> None:
    set_organization_vat(client, admin_token, "ATU00000000")
    partner = add_partner(client)
    fake_vies.answer = REQUESTER_REJECTED

    body = run_check(client, partner["id"]).json()

    assert body["status"] == "ERROR"
    assert body["message"] == (
        "VIES rejected your organisation's VAT number. "
        "Please check it in the organisation settings. The number was not confirmed."
    )
    # Retrying will not help: no "try again later", and VIES was asked only once.
    assert "try again" not in body["message"].lower()
    assert fake_vies.checked == ["ATU12345678"]


def test_invalid_result(client: TestClient, fake_vies) -> None:
    partner = add_partner(client)
    fake_vies.answer = INVALID_ANSWER

    body = run_check(client, partner["id"]).json()

    assert body["status"] == "FINDING"
    assert body["company_name"] is None
    assert body["address"] is None
    assert "not valid" in body["message"]


def test_error_result_is_stored_and_explained(
    client: TestClient, db: Session, fake_vies
) -> None:
    partner = add_partner(client)
    fake_vies.answer = {
        "error": "NO_ANSWER_IN_TIME",
        "message": "No answer within 8 s.",
    }

    response = run_check(client, partner["id"])

    # The check ran; "could not confirm" is a result, not a failed request.
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ERROR"
    assert "did not answer in time" in body["message"]
    assert db.scalar(select(CheckResult.status)) == "ERROR"


def test_list_shows_latest_result_after_reload(client: TestClient, fake_vies) -> None:
    checked = add_partner(client, "ATU11111111")
    not_checked = add_partner(client, "ATU22222222")

    fake_vies.answer = {"error": "NOT_REACHABLE"}
    run_check(client, checked["id"])
    fake_vies.answer = INVALID_ANSWER
    latest = run_check(client, checked["id"]).json()

    partners = {
        p["vat_number"]: p for p in client.get("/api/v1/partners").json()["items"]
    }

    assert partners["ATU11111111"]["latest_vies_check"] == latest
    assert partners["ATU22222222"]["latest_vies_check"] is None
    assert not_checked["id"] == partners["ATU22222222"]["id"]


def test_every_check_is_kept(client: TestClient, db: Session) -> None:
    partner = add_partner(client)

    run_check(client, partner["id"])
    run_check(client, partner["id"])

    assert db.query(CheckResult).count() == 2


def test_unknown_partner_gives_404(client: TestClient, fake_vies) -> None:
    response = run_check(client, str(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "partner_not_found"
    assert fake_vies.checked == []


def test_partner_of_another_organization_gives_404(
    client: TestClient, db: Session, fake_vies
) -> None:
    other = Organization(name="Other organization")
    db.add(other)
    db.flush()
    foreign = Partner(organization_id=other.id, vat_number="DE123456789")
    db.add(foreign)
    db.flush()

    response = run_check(client, str(foreign.id))

    assert response.status_code == 404
    assert fake_vies.checked == []


def test_other_organizations_results_are_not_listed(
    client: TestClient, db: Session
) -> None:
    other = Organization(name="Other organization")
    db.add(other)
    db.flush()
    foreign = Partner(organization_id=other.id, vat_number="DE123456789")
    db.add(foreign)
    db.flush()
    db.add(
        CheckResult(partner_id=foreign.id, source="VIES", status="OK", raw_response={})
    )
    db.flush()

    add_partner(client)
    partners = client.get("/api/v1/partners").json()["items"]

    assert [p["vat_number"] for p in partners] == ["ATU12345678"]
    assert partners[0]["latest_vies_check"] is None


def test_malformed_partner_id_uses_error_format(client: TestClient) -> None:
    response = run_check(client, "not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"
    assert response.json()["detail"]["field"] == "partner_id"


def test_old_checks_without_stored_explanation_are_still_explained(
    client: TestClient, db: Session
) -> None:
    partner = add_partner(client)
    db.add(
        CheckResult(
            partner_id=uuid.UUID(partner["id"]),
            source="VIES",
            status="FINDING",
            raw_response=INVALID_ANSWER,
        )
    )
    db.flush()

    check = client.get("/api/v1/partners").json()["items"][0]["latest_vies_check"]

    assert check["status"] == "FINDING"
    assert "not valid" in check["message"]


def test_partner_without_vat_number_cannot_be_checked_in_vies(
    client: TestClient, db: Session, fake_vies
) -> None:
    response = client.post(
        "/api/v1/partners", json={"company_register_number": "123456a"}
    )
    partner = response.json()

    check = run_check(client, partner["id"])

    assert check.status_code == 409
    assert check.json()["detail"]["code"] == "no_vat_number"
    assert check.json()["detail"]["field"] == "vat_number"
    # VIES was not asked and nothing was stored.
    assert fake_vies.checked == []
    assert db.query(CheckResult).count() == 0
