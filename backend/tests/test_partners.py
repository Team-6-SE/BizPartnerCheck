import uuid

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
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


def test_missing_vat_number_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/partners", json={})

    # Same error format as every other error (code, message, field).
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"
    assert response.json()["detail"]["field"] == "vat_number"
    assert response.json()["detail"]["message"]


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
