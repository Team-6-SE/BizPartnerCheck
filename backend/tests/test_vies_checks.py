"""API: run a VIES check for a partner and show the latest result (fake VIES)."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.vies import CheckStatus, ViesResult
from app.db.models import CheckResult, Organization, Partner

INVALID_ANSWER = {"isValid": False, "userError": "INVALID", "name": "---"}


def add_partner(client: TestClient, vat_number: str = "ATU12345678") -> dict:
    response = client.post("/api/v1/partners", json={"vat_number": vat_number})
    assert response.status_code == 201
    return response.json()


def run_check(client: TestClient, partner_id: str):
    return client.post(f"/api/v1/partners/{partner_id}/checks/vies")


def test_new_partner_has_no_check_yet(client: TestClient) -> None:
    partner = add_partner(client)

    assert partner["latest_vies_check"] is None
    assert client.get("/api/v1/partners").json()[0]["latest_vies_check"] is None


def test_valid_result_is_returned_and_stored(
    client: TestClient, db: Session, fake_vies
) -> None:
    partner = add_partner(client)

    response = run_check(client, partner["id"])

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "VALID"
    assert body["source"] == "VIES"
    assert body["company_name"] == "Muster Bau GmbH"
    assert body["message"]
    assert fake_vies.checked == ["ATU12345678"]

    stored = db.get(CheckResult, uuid.UUID(body["id"]))
    assert stored is not None
    assert stored.partner_id == uuid.UUID(partner["id"])
    assert stored.status == "VALID"
    assert stored.raw_response["userError"] == "VALID"
    # Stored with the time of the check.
    assert abs(stored.checked_at - datetime.now(UTC)) < timedelta(minutes=1)


def test_invalid_result(client: TestClient, fake_vies) -> None:
    partner = add_partner(client)
    fake_vies.result = ViesResult(CheckStatus.INVALID, INVALID_ANSWER)

    body = run_check(client, partner["id"]).json()

    assert body["status"] == "INVALID"
    assert body["company_name"] is None
    assert "not valid" in body["message"]


def test_error_result_is_stored_and_explained(
    client: TestClient, db: Session, fake_vies
) -> None:
    partner = add_partner(client)
    fake_vies.result = ViesResult(
        CheckStatus.ERROR,
        {"error": "NO_ANSWER_IN_TIME", "message": "No answer within 8 s."},
    )

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

    fake_vies.result = ViesResult(CheckStatus.ERROR, {"error": "NOT_REACHABLE"})
    run_check(client, checked["id"])
    fake_vies.result = ViesResult(CheckStatus.INVALID, INVALID_ANSWER)
    latest = run_check(client, checked["id"]).json()

    partners = {p["vat_number"]: p for p in client.get("/api/v1/partners").json()}

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
        CheckResult(
            partner_id=foreign.id, source="VIES", status="VALID", raw_response={}
        )
    )
    db.flush()

    add_partner(client)
    partners = client.get("/api/v1/partners").json()

    assert [p["vat_number"] for p in partners] == ["ATU12345678"]
    assert partners[0]["latest_vies_check"] is None


def test_malformed_partner_id_uses_error_format(client: TestClient) -> None:
    response = run_check(client, "not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"
    assert response.json()["detail"]["field"] == "partner_id"
