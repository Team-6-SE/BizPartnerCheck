from datetime import UTC, datetime, timedelta
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.models import CheckResult, Organization, Partner
from app.db.session import get_db
from app.main import app
from app.tenancy import TEST_ORGANIZATION_ID


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_valid_vat_number_is_saved(client: TestClient, db: Session) -> None:
    response = client.post("/api/v1/partners", json={"vat_number": "atu 123 456 78"})

    assert response.status_code == 201
    body = response.json()
    assert body["vat_number"] == "ATU12345678"

    saved = db.get(Partner, uuid.UUID(body["id"]))
    assert saved is not None
    assert saved.vat_number == "ATU12345678"
    assert saved.organization_id == TEST_ORGANIZATION_ID


def test_wrong_format_is_rejected(client: TestClient, db: Session) -> None:
    response = client.post("/api/v1/partners", json={"vat_number": "ATX1"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_vat_format"
    assert response.json()["detail"]["field"] == "vat_number"
    assert "ATU12345678" in response.json()["detail"]["message"]
    assert db.query(Partner).count() == 0


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"vat_number": "", "company_register_number": "  "},
        {"vat_number": None, "company_register_number": None},
    ],
)
def test_partner_without_any_number_is_rejected(
    client: TestClient, db: Session, body: dict
) -> None:
    response = client.post("/api/v1/partners", json=body)

    # Same error format as every other error (code, message, field).
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "missing_identifier"
    assert response.json()["detail"]["field"] == "vat_number"
    assert "company register number" in response.json()["detail"]["message"]
    assert db.query(Partner).count() == 0


def test_wrong_type_uses_the_uniform_error_format(client: TestClient) -> None:
    response = client.post("/api/v1/partners", json={"vat_number": ["ATU12345678"]})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"
    assert response.json()["detail"]["field"] == "vat_number"


def test_duplicate_is_rejected(client: TestClient, db: Session) -> None:
    first = client.post("/api/v1/partners", json={"vat_number": "ATU12345678"})
    # Same number, written differently: still a duplicate after normalising.
    second = client.post("/api/v1/partners", json={"vat_number": "atu 12345678"})

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "duplicate_partner"
    assert db.query(Partner).count() == 1


def test_same_vat_number_is_allowed_in_another_organization(
    client: TestClient, db: Session
) -> None:
    other = Organization(name="Other organization")
    db.add(other)
    db.flush()
    db.add(Partner(organization_id=other.id, vat_number="ATU12345678"))
    db.flush()

    response = client.post("/api/v1/partners", json={"vat_number": "ATU12345678"})

    assert response.status_code == 201


def test_list_shows_only_own_partners(client: TestClient, db: Session) -> None:
    other = Organization(name="Other organization")
    db.add(other)
    db.flush()
    db.add(Partner(organization_id=other.id, vat_number="DE123456789"))
    db.flush()

    client.post("/api/v1/partners", json={"vat_number": "ATU11111111"})
    client.post("/api/v1/partners", json={"vat_number": "ATU22222222"})

    response = client.get("/api/v1/partners")

    assert response.status_code == 200
    vat_numbers = [partner["vat_number"] for partner in response.json()["items"]]
    assert set(vat_numbers) == {"ATU11111111", "ATU22222222"}


def test_database_down_gives_clear_503(client: TestClient) -> None:
    def broken_db() -> Session:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    app.dependency_overrides[get_db] = broken_db

    response = client.get("/api/v1/partners")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_unavailable"


# --- company register number (S3.1, SCRUM-30) ---------------------------------


def test_partner_with_register_number_only_is_saved(
    client: TestClient, db: Session
) -> None:
    response = client.post(
        "/api/v1/partners", json={"company_register_number": "FN 123.456 A"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["company_register_number"] == "123456a"
    assert body["vat_number"] is None

    saved = db.get(Partner, uuid.UUID(body["id"]))
    assert saved is not None
    assert saved.company_register_number == "123456a"
    assert saved.vat_number is None


def test_partner_with_both_numbers_is_saved(client: TestClient) -> None:
    response = client.post(
        "/api/v1/partners",
        json={"vat_number": "ATU12345678", "company_register_number": "fn 33209m"},
    )

    assert response.status_code == 201
    assert response.json()["vat_number"] == "ATU12345678"
    assert response.json()["company_register_number"] == "33209m"


def test_wrong_register_number_format_is_rejected(
    client: TestClient, db: Session
) -> None:
    response = client.post(
        "/api/v1/partners", json={"company_register_number": "1234567"}
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_register_number_format"
    assert detail["field"] == "company_register_number"
    assert "123456a" in detail["message"]
    assert db.query(Partner).count() == 0


def test_wrong_register_number_is_rejected_even_with_a_valid_vat_number(
    client: TestClient, db: Session
) -> None:
    response = client.post(
        "/api/v1/partners",
        json={"vat_number": "ATU12345678", "company_register_number": "abc"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "company_register_number"
    assert db.query(Partner).count() == 0


def test_error_names_the_vat_field_when_both_numbers_are_wrong(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/partners",
        json={"vat_number": "ATX1", "company_register_number": "abc"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "vat_number"


def test_duplicate_register_number_is_rejected(client: TestClient, db: Session) -> None:
    first = client.post("/api/v1/partners", json={"company_register_number": "123456a"})
    # Same number, written differently: still a duplicate after normalising.
    second = client.post(
        "/api/v1/partners",
        json={"vat_number": "ATU87654321", "company_register_number": "FN 123456 A"},
    )

    assert first.status_code == 201
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "duplicate_partner"
    assert detail["field"] == "company_register_number"
    assert "123456a" in detail["message"]
    assert db.query(Partner).count() == 1


def test_duplicate_vat_number_is_reported_with_both_numbers_given(
    client: TestClient, db: Session
) -> None:
    client.post("/api/v1/partners", json={"vat_number": "ATU12345678"})

    response = client.post(
        "/api/v1/partners",
        json={"vat_number": "ATU12345678", "company_register_number": "123456a"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["field"] == "vat_number"
    assert db.query(Partner).count() == 1


def test_several_partners_without_register_number_are_allowed(
    client: TestClient,
) -> None:
    first = client.post("/api/v1/partners", json={"vat_number": "ATU11111111"})
    second = client.post("/api/v1/partners", json={"vat_number": "ATU22222222"})

    assert first.status_code == 201
    assert second.status_code == 201


def test_same_register_number_is_allowed_in_another_organization(
    client: TestClient, db: Session
) -> None:
    other = Organization(name="Other organization")
    db.add(other)
    db.flush()
    db.add(Partner(organization_id=other.id, company_register_number="123456a"))
    db.flush()

    response = client.post(
        "/api/v1/partners", json={"company_register_number": "123456a"}
    )

    assert response.status_code == 201


def test_list_shows_the_register_number(client: TestClient) -> None:
    client.post("/api/v1/partners", json={"company_register_number": "123456a"})

    partners = client.get("/api/v1/partners").json()["items"]

    assert partners[0]["company_register_number"] == "123456a"
    assert partners[0]["vat_number"] is None
    assert partners[0]["latest_vies_check"] is None


def test_database_refuses_a_partner_without_any_number(db: Session) -> None:
    db.add(Partner(organization_id=TEST_ORGANIZATION_ID))

    with pytest.raises(IntegrityError) as error:
        db.flush()
    db.rollback()

    assert "ck_partners_identifier" in str(error.value)


# --- Partner search and pagination (UM-126) -------------------------------


def test_search_by_company_name_is_case_insensitive(client: TestClient) -> None:
    client.post(
        "/api/v1/partners",
        json={"vat_number": "ATU11111111", "company_name": "Muster Bau GmbH"},
    )
    client.post(
        "/api/v1/partners",
        json={"vat_number": "ATU22222222", "company_name": "Other Company"},
    )

    response = client.get("/api/v1/partners?search=mUsTeR")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["company_name"] == "Muster Bau GmbH"


def test_search_by_vat_number(client: TestClient) -> None:
    client.post("/api/v1/partners", json={"vat_number": "ATU11111111"})
    client.post("/api/v1/partners", json={"vat_number": "ATU22222222"})

    response = client.get("/api/v1/partners?search=111111")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["vat_number"] == "ATU11111111"


def test_search_by_company_register_number(client: TestClient) -> None:
    client.post(
        "/api/v1/partners",
        json={"company_register_number": "123456a"},
    )
    client.post(
        "/api/v1/partners",
        json={"company_register_number": "654321b"},
    )

    response = client.get("/api/v1/partners?search=123456")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["company_register_number"] == "123456a"


def test_partner_pagination(client: TestClient) -> None:
    for number in range(1, 6):
        client.post(
            "/api/v1/partners",
            json={"vat_number": f"ATU{number:08d}"},
        )

    first_page = client.get(
        "/api/v1/partners?page=1&page_size=2&sort_by=vat_number&sort_order=asc"
    ).json()

    second_page = client.get(
        "/api/v1/partners?page=2&page_size=2&sort_by=vat_number&sort_order=asc"
    ).json()

    assert first_page["total"] == 5
    assert first_page["page"] == 1
    assert first_page["page_size"] == 2
    assert first_page["total_pages"] == 3
    assert len(first_page["items"]) == 2

    assert second_page["page"] == 2
    assert len(second_page["items"]) == 2

    first_ids = {partner["id"] for partner in first_page["items"]}
    second_ids = {partner["id"] for partner in second_page["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_partner_sorting_ascending_and_descending(client: TestClient) -> None:
    for vat_number in ["ATU33333333", "ATU11111111", "ATU22222222"]:
        client.post("/api/v1/partners", json={"vat_number": vat_number})

    ascending = client.get("/api/v1/partners?sort_by=vat_number&sort_order=asc").json()

    descending = client.get(
        "/api/v1/partners?sort_by=vat_number&sort_order=desc"
    ).json()

    ascending_numbers = [partner["vat_number"] for partner in ascending["items"]]
    descending_numbers = [partner["vat_number"] for partner in descending["items"]]

    assert ascending_numbers == [
        "ATU11111111",
        "ATU22222222",
        "ATU33333333",
    ]
    assert descending_numbers == [
        "ATU33333333",
        "ATU22222222",
        "ATU11111111",
    ]


def test_invalid_sort_field_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/partners?sort_by=unknown")

    assert response.status_code == 422


# --- Partner detail and check history (SCRUM-58) ----------------------------


def test_get_partner_details(client: TestClient) -> None:
    created = client.post(
        "/api/v1/partners",
        json={
            "vat_number": "ATU12345678",
            "company_name": "Muster Bau GmbH",
        },
    )
    partner_id = created.json()["id"]

    response = client.get(f"/api/v1/partners/{partner_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == partner_id
    assert body["vat_number"] == "ATU12345678"
    assert body["company_name"] == "Muster Bau GmbH"
    assert body["is_archived"] is False


def test_get_partner_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/partners/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "partner_not_found"


def test_partner_details_cannot_access_another_organization(
    client: TestClient, db: Session
) -> None:
    other = Organization(name="Other organization")
    db.add(other)
    db.flush()

    partner = Partner(
        organization_id=other.id,
        vat_number="DE123456789",
    )
    db.add(partner)
    db.flush()

    response = client.get(f"/api/v1/partners/{partner.id}")

    assert response.status_code == 404


def test_partner_check_history_is_newest_first(client: TestClient, db: Session) -> None:
    created = client.post(
        "/api/v1/partners",
        json={"vat_number": "ATU12345678"},
    )
    partner_id = uuid.UUID(created.json()["id"])

    older_time = datetime.now(UTC) - timedelta(days=2)
    newer_time = datetime.now(UTC) - timedelta(days=1)

    older_check = CheckResult(
        partner_id=partner_id,
        source="vies",
        status="OK",
        checked_at=older_time,
        raw_response={"isValid": True},
        explanation="VAT number is valid.",
    )
    newer_check = CheckResult(
        partner_id=partner_id,
        source="vies",
        status="FINDING",
        checked_at=newer_time,
        raw_response={"isValid": False},
        explanation="VAT number is invalid.",
    )

    db.add_all([older_check, newer_check])
    db.flush()

    response = client.get(f"/api/v1/partners/{partner_id}/checks")

    assert response.status_code == 200
    body = response.json()

    assert len(body) == 2
    assert body[0]["status"] == "FINDING"
    assert body[1]["status"] == "OK"
    assert body[0]["checked_at"] > body[1]["checked_at"]

    # Reading the history must not modify the stored records.
    assert db.get(CheckResult, older_check.id) is not None
    assert db.get(CheckResult, newer_check.id) is not None


def test_partner_check_history_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/partners/{uuid.uuid4()}/checks")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "partner_not_found"


def test_partner_search_with_10000_partners(client: TestClient, db: Session) -> None:
    partners = [
        Partner(
            organization_id=TEST_ORGANIZATION_ID,
            company_name=f"Performance Test Company {i:05d}",
            vat_number=f"ATU{i + 10000000:08d}",
        )
        for i in range(10000)
    ]

    db.add_all(partners)
    db.flush()

    import time

    start = time.perf_counter()

    response = client.get(
        "/api/v1/partners",
        params={"search": "Performance Test Company 09999"},
    )

    elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert elapsed < 2.0, f"Search took {elapsed:.3f} seconds"


def test_organizations_cannot_access_each_others_partners(
    anonymous_client: TestClient, db: Session, tokens
) -> None:
    other_org = Organization(name="Isolation test organization")
    db.add(other_org)
    db.flush()

    own_partner = Partner(
        organization_id=TEST_ORGANIZATION_ID,
        vat_number="ATU11111111",
    )
    other_partner = Partner(
        organization_id=other_org.id,
        vat_number="ATU22222222",
    )
    db.add_all([own_partner, other_partner])
    db.flush()

    token_a = tokens.make()
    token_b = tokens.make(extra={"organization_id": str(other_org.id)})

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    response_a = anonymous_client.get("/api/v1/partners", headers=headers_a)
    response_b = anonymous_client.get("/api/v1/partners", headers=headers_b)

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    assert {p["id"] for p in response_a.json()["items"]} == {str(own_partner.id)}
    assert {p["id"] for p in response_b.json()["items"]} == {str(other_partner.id)}

    for source in ("vies", "bmf"):
        response = anonymous_client.post(
            f"/api/v1/partners/{other_partner.id}/checks/{source}",
            headers=headers_a,
        )
        assert response.status_code == 404

        response = anonymous_client.post(
            f"/api/v1/partners/{own_partner.id}/checks/{source}",
            headers=headers_b,
        )
        assert response.status_code == 404


def test_post_same_vat_from_two_different_organization_tokens(
    anonymous_client: TestClient, db: Session, tokens
) -> None:
    other = Organization(name="Second token customer")
    db.add(other)
    db.flush()
    vat = {"vat_number": "ATU78787878"}

    def create_for(org_id: uuid.UUID):
        return anonymous_client.post(
            "/api/v1/partners",
            json=vat,
            headers={
                "Authorization": f"Bearer {tokens.make(extra={'organization_id': str(org_id)})}"
            },
        )

    first = create_for(TEST_ORGANIZATION_ID)
    second = create_for(other.id)
    assert first.status_code == second.status_code == 201
    saved = db.query(Partner).filter(Partner.vat_number == vat["vat_number"]).all()
    assert {row.organization_id for row in saved} == {TEST_ORGANIZATION_ID, other.id}
