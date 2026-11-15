from unittest.mock import Mock

import pytest

from app.registration import router as registration_module
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
    fake_keycloak.assign_org_admin_role.assert_called_once_with(
        "test-user-id"
    )
    fake_keycloak.send_verification_email.assert_called_once_with(
        "test-user-id"
    )


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
            json=registration_data(
                website=f"bot-{number}.example"
            ),
        )
        responses.append(response.status_code)

    assert responses == [400, 400, 400, 400, 400, 429]
    fake_keycloak.create_user.assert_not_called()