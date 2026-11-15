import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.models import Organization, Partner
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
    vat_numbers = [partner["vat_number"] for partner in response.json()]
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

    partners = client.get("/api/v1/partners").json()

    assert partners[0]["company_register_number"] == "123456a"
    assert partners[0]["vat_number"] is None
    assert partners[0]["latest_vies_check"] is None


def test_database_refuses_a_partner_without_any_number(db: Session) -> None:
    db.add(Partner(organization_id=TEST_ORGANIZATION_ID))

    with pytest.raises(IntegrityError) as error:
        db.flush()
    db.rollback()

    assert "ck_partners_identifier" in str(error.value)
