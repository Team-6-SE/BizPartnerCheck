"""Keycloak operations used during customer registration.

The API creates the first admin of a new organisation with its own Keycloak client
(bizpartnercheck-registration, may only manage users). Locally the secret from the
realm file is used; on any other OIDC_ISSUER KEYCLOAK_REGISTRATION_CLIENT_SECRET must
be set, otherwise registration answers "temporarily unavailable" (never a known secret).
"""

import os
import uuid

import httpx2 as httpx

from app.auth import DEFAULT_ISSUER


DEFAULT_CLIENT_ID = "bizpartnercheck-registration"
LOCAL_DEV_SECRET = "local-registration-only-change-in-production"
# Where "Back to application" leads after the e-mail is verified and the password set.
# The same APP_BASE_URL fills the allowed redirect URLs in the realm file.
DEFAULT_APP_URL = "http://localhost:5173"


class KeycloakRegistrationError(Exception):
    """Keycloak registration operation failed."""


class KeycloakRegistrationClient:
    def __init__(self) -> None:
        issuer = os.environ.get("OIDC_ISSUER") or DEFAULT_ISSUER
        base_url = os.environ.get("KEYCLOAK_API_BASE_URL") or issuer

        self.token_url = f"{base_url}/protocol/openid-connect/token"
        self.admin_url = base_url.replace("/realms/", "/admin/realms/", 1)

        self.client_id = (
            os.environ.get("KEYCLOAK_REGISTRATION_CLIENT_ID") or DEFAULT_CLIENT_ID
        )
        secret = os.environ.get("KEYCLOAK_REGISTRATION_CLIENT_SECRET")
        if not secret and issuer == DEFAULT_ISSUER:
            secret = LOCAL_DEV_SECRET
        self.client_secret = secret
        app_url = os.environ.get("APP_BASE_URL") or DEFAULT_APP_URL
        self.app_url = app_url.rstrip("/") + "/"

        self.http = httpx.Client(timeout=10)

    def close(self) -> None:
        self.http.close()

    def _token(self) -> str:
        if not self.client_secret:
            raise KeycloakRegistrationError(
                "KEYCLOAK_REGISTRATION_CLIENT_SECRET is not set."
            )
        try:
            response = self.http.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            response.raise_for_status()
            return response.json()["access_token"]
        except (httpx.HTTPError, KeyError) as exc:
            raise KeycloakRegistrationError(
                "Could not authenticate with Keycloak."
            ) from exc

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def create_user(
        self,
        email: str,
        admin_name: str,
        organization_id: uuid.UUID,
    ) -> str:
        name_parts = admin_name.strip().split(maxsplit=1)

        payload = {
            "username": email,
            "email": email,
            "emailVerified": False,
            "enabled": True,
            "requiredActions": ["VERIFY_EMAIL"],
            "firstName": name_parts[0],
            "lastName": name_parts[1] if len(name_parts) > 1 else "",
            "attributes": {"organization_id": [str(organization_id)]},
        }

        try:
            response = self.http.post(
                f"{self.admin_url}/users",
                json=payload,
                headers=self._headers(),
            )

            if response.status_code == 409:
                raise KeycloakRegistrationError(
                    "This email address is already registered."
                )

            response.raise_for_status()

            location = response.headers.get("Location")
            if not location:
                raise KeycloakRegistrationError(
                    "Keycloak did not return the new user ID."
                )

            return location.rstrip("/").split("/")[-1]

        except httpx.HTTPError as exc:
            raise KeycloakRegistrationError(
                "Could not create the Keycloak user."
            ) from exc

    def assign_org_admin_role(self, user_id: str) -> None:
        try:
            role_response = self.http.get(
                f"{self.admin_url}/roles/org-admin",
                headers=self._headers(),
            )
            role_response.raise_for_status()
            role = role_response.json()

            response = self.http.post(
                f"{self.admin_url}/users/{user_id}/role-mappings/realm",
                json=[role],
                headers=self._headers(),
            )
            response.raise_for_status()

        except httpx.HTTPError as exc:
            raise KeycloakRegistrationError(
                "Could not assign the organization admin role."
            ) from exc

    def delete_user(self, user_id: str) -> None:
        try:
            response = self.http.delete(
                f"{self.admin_url}/users/{user_id}",
                headers=self._headers(),
            )
            response.raise_for_status()

        except httpx.HTTPError as exc:
            raise KeycloakRegistrationError(
                "Could not roll back the Keycloak user."
            ) from exc

    def send_verification_email(self, user_id: str) -> None:
        try:
            response = self.http.put(
                f"{self.admin_url}/users/{user_id}/execute-actions-email",
                headers=self._headers(),
                params={
                    "client_id": "bizpartnercheck-web",
                    "redirect_uri": self.app_url,
                    "lifespan": 86400,
                },
                json=["VERIFY_EMAIL", "UPDATE_PASSWORD"],
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise KeycloakRegistrationError(
                "Could not send the email verification and password setup link."
            ) from exc
