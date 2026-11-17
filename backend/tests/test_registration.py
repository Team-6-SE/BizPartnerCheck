from unittest.mock import Mock

import httpx2 as httpx
import pytest
from sqlalchemy import select

from app.db.models import Organization
from app.registration import router as registration_module
from app.security import keycloak_registration as kr
from app.security.keycloak_registration import KeycloakRegistrationError


@pytest.fixture(autouse=True)
def reset_rate_limit():
    """Give every test a clean rate-limit state."""
    registration_module._registration_attempts.clear()


@pytest.fixture
def fake_keycloak(monkeypatch):
    """Replace Keycloak with a mock."""
    keycloak = Mock()
    keycloak.create_user.return_value = "test-user-id"

    monkeypatch.setattr(
        registration_module,
        "KeycloakRegistrationClient",
        lambda: keycloak,
    )

    return keycloak


def registration_data(**overrides):
    data = {
        "company_name": "Test Company",
        "admin_name": "Test Administrator",
        "email": "test@example.com",
        "vat_number": None,
        "website": "",
    }
    data.update(overrides)
    return data


def test_successful_registration(anonymous_client, db, fake_keycloak):
    response = anonymous_client.post(
        "/api/v1/registration",
        json=registration_data(),
    )

    assert response.status_code == 201
    assert "verification" in response.json()["message"].lower()

    fake_keycloak.create_user.assert_called_once()
    fake_keycloak.assign_org_admin_role.assert_called_once_with("test-user-id")
    fake_keycloak.send_verification_email.assert_called_once_with("test-user-id")


def test_duplicate_email_is_rejected(anonymous_client, fake_keycloak):
    fake_keycloak.create_user.side_effect = KeycloakRegistrationError(
        "This email address is already registered."
    )

    response = anonymous_client.post(
        "/api/v1/registration",
        json=registration_data(),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "email_already_registered"


def test_invalid_email_is_rejected(anonymous_client):
    response = anonymous_client.post(
        "/api/v1/registration",
        json=registration_data(email="invalid-email"),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_email"


def test_honeypot_rejects_registration(anonymous_client, fake_keycloak):
    response = anonymous_client.post(
        "/api/v1/registration",
        json=registration_data(website="https://spam.example"),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "registration_rejected"
    fake_keycloak.create_user.assert_not_called()


def test_rate_limit_blocks_sixth_attempt(anonymous_client, fake_keycloak):
    responses = []

    for number in range(6):
        response = anonymous_client.post(
            "/api/v1/registration",
            json=registration_data(website=f"bot-{number}.example"),
        )
        responses.append(response.status_code)

    assert responses == [400, 400, 400, 400, 400, 429]
    fake_keycloak.create_user.assert_not_called()


# --- Organisation and admin are created together or not at all (S2.2) ------------


def organizations_named(db, name):
    return db.scalars(select(Organization).where(Organization.name == name)).all()


def test_registration_creates_the_organization_for_the_new_admin(
    anonymous_client, db, fake_keycloak
):
    response = anonymous_client.post(
        "/api/v1/registration",
        json=registration_data(company_name="Neu GmbH", vat_number="atu 123 456 75"),
    )

    assert response.status_code == 201
    [organization] = organizations_named(db, "Neu GmbH")
    assert organization.vat_number == "ATU12345675"
    kwargs = fake_keycloak.create_user.call_args.kwargs
    assert kwargs["organization_id"] == organization.id
    assert kwargs["email"] == "test@example.com"


@pytest.mark.parametrize(
    "failing_step", ["assign_org_admin_role", "send_verification_email"]
)
def test_failed_keycloak_step_removes_user_and_organization(
    anonymous_client, db, fake_keycloak, failing_step
):
    getattr(fake_keycloak, failing_step).side_effect = KeycloakRegistrationError("down")

    response = anonymous_client.post(
        "/api/v1/registration", json=registration_data(company_name="Halb GmbH")
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "registration_unavailable"
    fake_keycloak.delete_user.assert_called_once_with("test-user-id")
    assert organizations_named(db, "Halb GmbH") == []


def test_unexpected_error_also_removes_the_keycloak_user(
    anonymous_client, db, fake_keycloak
):
    fake_keycloak.send_verification_email.side_effect = RuntimeError("bug")

    with pytest.raises(RuntimeError):
        anonymous_client.post(
            "/api/v1/registration", json=registration_data(company_name="Bug GmbH")
        )

    fake_keycloak.delete_user.assert_called_once_with("test-user-id")
    assert organizations_named(db, "Bug GmbH") == []


def test_invalid_vat_number_is_shown_at_the_field(anonymous_client, fake_keycloak):
    response = anonymous_client.post(
        "/api/v1/registration", json=registration_data(vat_number="ATU1")
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_vat_format"
    assert response.json()["detail"]["field"] == "vat_number"
    fake_keycloak.create_user.assert_not_called()


def test_vat_number_of_an_existing_organization_is_rejected(
    anonymous_client, db, fake_keycloak
):
    db.add(Organization(name="First GmbH", vat_number="ATU12345675"))
    db.flush()

    response = anonymous_client.post(
        "/api/v1/registration", json=registration_data(vat_number="ATU12345675")
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "duplicate_organization_vat"
    assert response.json()["detail"]["field"] == "vat_number"
    fake_keycloak.create_user.assert_not_called()


# --- Registration client: no known secret outside local development -----------------


def test_local_development_uses_the_secret_from_the_realm_file(monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("KEYCLOAK_REGISTRATION_CLIENT_SECRET", raising=False)

    client = kr.KeycloakRegistrationClient()

    assert client.client_secret == kr.LOCAL_DEV_SECRET
    client.close()


def test_server_without_secret_refuses_instead_of_using_the_known_one(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", "https://auth.example.com/realms/bizpartnercheck")
    monkeypatch.delenv("KEYCLOAK_REGISTRATION_CLIENT_SECRET", raising=False)

    client = kr.KeycloakRegistrationClient()

    assert client.client_secret is None
    with pytest.raises(KeycloakRegistrationError):
        client.create_user("a@example.com", "Anna", organization_id=None)
    client.close()


def test_verification_mail_leads_back_to_the_app(monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t"})
        sent.append(request)
        return httpx.Response(204)

    client = kr.KeycloakRegistrationClient()
    client.http = httpx.Client(transport=httpx.MockTransport(handler))

    client.send_verification_email("user-1")

    [request] = sent
    assert request.url.params["redirect_uri"] == "https://app.example.com/"
    assert request.url.params["client_id"] == "bizpartnercheck-web"
    client.close()
