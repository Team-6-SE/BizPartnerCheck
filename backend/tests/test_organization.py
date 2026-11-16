"""API: the organisation's own VAT number (the VIES requester), SCRUM-40."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.tenancy import TEST_ORGANIZATION_ID


def as_admin(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


def set_vat_number(client: TestClient, admin_token: str, vat_number: str | None):
    return client.put(
        "/api/v1/organization",
        json={"vat_number": vat_number},
        headers=as_admin(admin_token),
    )


def test_every_user_can_read_the_organization(client: TestClient) -> None:
    response = client.get("/api/v1/organization")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(TEST_ORGANIZATION_ID),
        "name": "Test organization",
        "vat_number": None,
    }


def test_only_admins_can_change_the_vat_number(client: TestClient, db: Session) -> None:
    response = client.put("/api/v1/organization", json={"vat_number": "ATU12345678"})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"
    assert db.get(Organization, TEST_ORGANIZATION_ID).vat_number is None


def test_admin_sets_the_vat_number_normalised(
    client: TestClient, db: Session, admin_token: str
) -> None:
    response = set_vat_number(client, admin_token, "atu 123.456-78")

    assert response.status_code == 200
    assert response.json()["vat_number"] == "ATU12345678"
    assert db.get(Organization, TEST_ORGANIZATION_ID).vat_number == "ATU12345678"
    assert client.get("/api/v1/organization").json()["vat_number"] == "ATU12345678"


@pytest.mark.parametrize("vat_number", ["ATU00000000X", "XX12345678", "12345678"])
def test_invalid_vat_number_is_refused_and_not_stored(
    client: TestClient, db: Session, admin_token: str, vat_number: str
) -> None:
    set_vat_number(client, admin_token, "ATU12345678")

    response = set_vat_number(client, admin_token, vat_number)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_vat_format"
    assert response.json()["detail"]["field"] == "vat_number"
    # The old number stays: a wrong one would make VIES refuse every check.
    assert db.get(Organization, TEST_ORGANIZATION_ID).vat_number == "ATU12345678"


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_value_removes_the_vat_number(
    client: TestClient, db: Session, admin_token: str, empty: str | None
) -> None:
    set_vat_number(client, admin_token, "ATU12345678")

    response = set_vat_number(client, admin_token, empty)

    assert response.status_code == 200
    assert response.json()["vat_number"] is None
    assert db.get(Organization, TEST_ORGANIZATION_ID).vat_number is None


def test_vies_is_asked_with_the_organization_vat_number(
    client: TestClient, admin_token: str, fake_vies
) -> None:
    set_vat_number(client, admin_token, "ATU12345678")
    partner = client.post("/api/v1/partners", json={"vat_number": "DE123456789"})

    client.post(f"/api/v1/partners/{partner.json()['id']}/checks/vies")

    assert fake_vies.requesters == ["ATU12345678"]


def test_vat_number_of_another_organization_is_refused(
    client: TestClient, db: Session, admin_token: str
) -> None:
    db.add(Organization(name="Other customer", vat_number="ATU12345675"))
    db.flush()

    response = set_vat_number(client, admin_token, "ATU12345675")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "organization_vat_taken"
    assert db.get(Organization, TEST_ORGANIZATION_ID).vat_number is None
