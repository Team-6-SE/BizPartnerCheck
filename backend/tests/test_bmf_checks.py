"""API: BMF check per partner and the platform admin import (S4.3). No internet needed."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.base import CheckStatus, CheckSubject, Scenario
from app.adapters.bmf import BmfAdapter
from app.adapters.fake import FakeAdapter
from app.bmf.importer import run_import
from app.bmf.router import get_feed_downloader
from app.db.models import CheckResult, Organization, Partner
from app.main import app

SAMPLE = Path(__file__).parent / "fixtures" / "bmf_feed_sample.xml"


def import_list(db: Session, hours_ago: float = 1) -> None:
    imported = datetime.now(UTC) - timedelta(hours=hours_ago)
    record = run_import(
        db, SAMPLE.read_bytes(), trigger="schedule", now=lambda: imported
    )
    assert record.status == "SUCCESS"


def add_partner(
    client: TestClient, vat_number: str | None, register_number: str | None = None
) -> dict:
    response = client.post(
        "/api/v1/partners",
        json={"vat_number": vat_number, "company_register_number": register_number},
    )
    assert response.status_code == 201, response.text
    return response.json()


def check_bmf(client: TestClient, partner_id: str) -> dict:
    response = client.post(f"/api/v1/partners/{partner_id}/checks/bmf")
    assert response.status_code == 201, response.text
    return response.json()


def vies_says_name(fake_vies, name: str) -> None:
    fake_vies.answer = {"isValid": True, "userError": "VALID", "name": name}


# --- matching (T4.3.3) ------------------------------------------------------------


def test_same_vat_number_is_finding_with_entry_and_date(
    client: TestClient, db: Session
) -> None:
    import_list(db)
    partner = add_partner(client, "ATU11111111")

    body = check_bmf(client, partner["id"])

    assert body["status"] == "FINDING"
    assert body["source"] == "BMF"
    assert "Muster Scheinbau GmbH" in body["message"]
    assert "3 Nov 2026" in body["message"]  # publication date
    stored = db.get(CheckResult, uuid.UUID(body["id"]))
    assert stored is not None
    assert stored.raw_response["match"] == "VAT_NUMBER"
    entry = stored.raw_response["matches"][0]
    assert entry["publishedOn"] == "2026-11-03"
    assert entry["registerNumber"] == "123456a"


def test_partner_without_vat_number_is_matched_by_register_number(
    client: TestClient, db: Session
) -> None:
    import_list(db)
    # Added by company register number only (S3.1); "FN 123456 A" is stored as "123456a".
    partner = add_partner(client, None, "FN 123456 A")

    body = check_bmf(client, partner["id"])

    assert body["status"] == "FINDING"
    assert "same Firmenbuch number" in body["message"]
    stored = db.get(CheckResult, uuid.UUID(body["id"]))
    assert stored is not None
    assert stored.raw_response["match"] == "REGISTER_NUMBER"
    assert stored.raw_response["checked"]["vatNumber"] is None


def test_partner_without_vat_number_and_no_match_is_ok(
    client: TestClient, db: Session
) -> None:
    import_list(db)
    partner = add_partner(client, None, "999999z")

    body = check_bmf(client, partner["id"])

    assert body["status"] == "OK"
    assert "Compared: company register number." in body["message"]


def test_register_number_match_with_vat_number_too(
    client: TestClient, db: Session
) -> None:
    import_list(db)
    # Another VAT number, but the Firmenbuch number of a listed company.
    partner = add_partner(client, "ATU44444444", "654321x")

    assert check_bmf(client, partner["id"])["status"] == "FINDING"


def test_kennziffer_des_ur_also_matches(client: TestClient, db: Session) -> None:
    import_list(db)
    partner = add_partner(client, "ATU33333333")

    assert check_bmf(client, partner["id"])["status"] == "FINDING"


def test_uid_with_suffix_matches_the_plain_number(
    client: TestClient, db: Session
) -> None:
    import_list(db)
    partner = add_partner(client, "ATU22222222")

    assert check_bmf(client, partner["id"])["status"] == "FINDING"


def test_name_only_match_is_review_never_ok(
    client: TestClient, db: Session, fake_vies
) -> None:
    import_list(db)
    partner = add_partner(client, "ATU44444444")
    vies_says_name(fake_vies, "GLANZ REINIGUNG OG")
    client.post(f"/api/v1/partners/{partner['id']}/checks/vies")

    body = check_bmf(client, partner["id"])

    assert body["status"] == "REVIEW"
    assert "Possible match" in body["message"]
    assert "please review" in body["message"]
    assert "1 more" in body["message"]  # the name is on the list twice
    stored = db.get(CheckResult, uuid.UUID(body["id"]))
    assert stored is not None
    assert stored.raw_response["checked"]["name"] == "GLANZ REINIGUNG OG"
    assert stored.raw_response["matchCount"] == 2


def test_no_match_is_ok_and_says_what_was_compared(
    client: TestClient, db: Session, fake_vies
) -> None:
    import_list(db)
    partner = add_partner(client, "ATU44444444")

    without_name = check_bmf(client, partner["id"])
    vies_says_name(fake_vies, "Ganz Andere GmbH")
    client.post(f"/api/v1/partners/{partner['id']}/checks/vies")
    with_name = check_bmf(client, partner["id"])

    assert without_name["status"] == with_name["status"] == "OK"
    assert "Compared: VAT number." in without_name["message"]
    assert "names were not compared" in without_name["message"]
    assert "Compared: VAT number and company name." in with_name["message"]


def test_name_from_a_fake_vies_answer_is_not_used(
    client: TestClient, db: Session
) -> None:
    import_list(db)
    partner = add_partner(client, "ATU44444444")
    db.add(
        CheckResult(
            partner_id=uuid.UUID(partner["id"]),
            source="VIES",
            status="OK",
            raw_response={"isValid": True, "name": "Glanz Reinigung OG", "fake": True},
        )
    )
    db.flush()

    assert check_bmf(client, partner["id"])["status"] == "OK"


def test_removed_entry_is_not_matched(client: TestClient, db: Session) -> None:
    import_list(db)
    text = SAMPLE.read_bytes().decode("iso-8859-1")
    shorter = "\n".join(
        line for line in text.splitlines() if "Muster Scheinbau" not in line
    )
    run_import(db, shorter.encode("iso-8859-1"), trigger="schedule")
    partner = add_partner(client, "ATU11111111")

    assert check_bmf(client, partner["id"])["status"] == "OK"


def test_list_never_imported_is_error_not_ok(client: TestClient) -> None:
    partner = add_partner(client, "ATU11111111")

    body = check_bmf(client, partner["id"])

    assert body["status"] == "ERROR"
    assert "has not been imported yet" in body["message"]


# --- freshness (T4.3.4) -----------------------------------------------------------


def test_result_shows_how_current_the_list_was(client: TestClient, db: Session) -> None:
    import_list(db, hours_ago=2)
    partner = add_partner(client, "ATU44444444")

    body = check_bmf(client, partner["id"])

    age = datetime.fromisoformat(body["checked_at"]) - datetime.fromisoformat(
        body["data_as_of"]
    )
    assert timedelta(hours=1.9) < age < timedelta(hours=2.1)
    assert "Warning" not in body["message"]


@pytest.mark.parametrize("vat_number", ["ATU44444444", "ATU11111111"])
def test_list_older_than_24_hours_gives_a_warning(
    client: TestClient, db: Session, vat_number: str
) -> None:
    import_list(db, hours_ago=30)
    partner = add_partner(client, vat_number)

    body = check_bmf(client, partner["id"])

    assert body["status"] in ("OK", "FINDING")  # the status is kept
    assert "older than 24 hours" in body["message"]


# --- API ---------------------------------------------------------------------------


def test_partner_list_shows_latest_bmf_and_vies_result(
    client: TestClient, db: Session
) -> None:
    import_list(db)
    partner = add_partner(client, "ATU11111111")
    client.post(f"/api/v1/partners/{partner['id']}/checks/vies")
    bmf = check_bmf(client, partner["id"])

    listed = client.get("/api/v1/partners").json()[0]

    assert listed["latest_bmf_check"] == bmf
    assert listed["latest_vies_check"]["source"] == "VIES"


def test_bmf_check_of_another_organizations_partner_is_404(
    client: TestClient, db: Session
) -> None:
    other = Organization(name="Other organization")
    db.add(other)
    db.flush()
    foreign = Partner(organization_id=other.id, vat_number="ATU11111111")
    db.add(foreign)
    db.flush()

    response = client.post(f"/api/v1/partners/{foreign.id}/checks/bmf")

    assert response.status_code == 404


# --- fake BMF adapter -----------------------------------------------------------


@pytest.mark.parametrize(
    ("scenario", "status"),
    [(Scenario.OK, CheckStatus.OK), (Scenario.FINDING, CheckStatus.FINDING)],
)
def test_fake_bmf_needs_no_database(scenario: Scenario, status: CheckStatus) -> None:
    def no_database():
        raise AssertionError("the fake must not use the database")

    adapter = FakeAdapter(BmfAdapter(no_database), scenario)

    result = adapter.check(CheckSubject(vat_number="ATU12345678"))

    assert result.status == status
    assert result.raw["fake"] is True
    assert result.data_as_of is not None


# --- platform admin: status and manual import (T4.3.2) ---------------------------


@pytest.fixture
def platform_admin(client: TestClient, tokens) -> TestClient:
    token = tokens.make(
        sub="ops-1",
        email="ops@example.com",
        extra={"realm_access": {"roles": ["platform-admin"]}},
    )
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def test_platform_admin_sees_last_import(
    platform_admin: TestClient, db: Session
) -> None:
    import_list(db)

    body = platform_admin.get("/api/v1/admin/bmf/status").json()

    assert body["entries_on_list"] == 6
    assert body["last_successful_import"]["status"] == "SUCCESS"
    assert body["last_successful_import"]["entries_in_feed"] == 6
    assert body["last_import"]["trigger"] == "schedule"


def test_platform_admin_starts_an_import(platform_admin: TestClient) -> None:
    app.dependency_overrides[get_feed_downloader] = lambda: SAMPLE.read_bytes

    response = platform_admin.post("/api/v1/admin/bmf/import")

    assert response.status_code == 200
    body = response.json()
    assert body["entries_on_list"] == 6
    assert body["last_import"]["trigger"] == "manual"
    assert body["last_import"]["started_by"] == "ops@example.com"


def test_failed_manual_import_is_shown(platform_admin: TestClient) -> None:
    def down() -> bytes:
        raise httpx.ConnectError("no route")

    app.dependency_overrides[get_feed_downloader] = lambda: down

    body = platform_admin.post("/api/v1/admin/bmf/import").json()

    assert body["last_import"]["status"] == "FAILED"
    assert body["last_successful_import"] is None


@pytest.mark.parametrize(
    "path", ["/api/v1/admin/bmf/status", "/api/v1/admin/bmf/import"]
)
def test_other_users_may_not_use_the_admin_routes(
    client: TestClient, admin_token: str, path: str
) -> None:
    method = client.get if path.endswith("status") else client.post

    normal_user = method(path)
    client.headers["Authorization"] = f"Bearer {admin_token}"
    org_admin = method(path)

    assert normal_user.status_code == 403
    assert org_admin.status_code == 403  # an organisation admin is not a platform admin
