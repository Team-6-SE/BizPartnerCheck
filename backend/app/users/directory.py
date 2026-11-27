"""Keycloak user administration using the existing registration service account.

This never uses the end user's access token as an Admin API credential. Every
returned user is rechecked against the organisation from the verified JWT.
"""

import uuid
from collections.abc import Iterator
from typing import Annotated, Any

import httpx2 as httpx
from fastapi import Depends, status

from app.errors import api_error
from app.security.keycloak_registration import (
    KeycloakRegistrationClient,
    KeycloakRegistrationError,
)

MANAGED_ROLES = frozenset({"org-admin", "checker", "reviewer"})
INVITE_LIFETIME = 7 * 24 * 60 * 60
PAGE_SIZE = 200
MAX_PAGES = 100


class KeycloakDirectory:
    def __init__(self) -> None:
        self._client = KeycloakRegistrationClient()

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.http.request(
                method,
                f"{self._client.admin_url}{path}",
                headers=self._client._headers(),
                **kwargs,
            )
        except (httpx.HTTPError, KeycloakRegistrationError) as exc:
            raise api_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "user_directory_unavailable",
                "User management is temporarily unavailable.",
            ) from exc
        if response.status_code == 404:
            raise api_error(status.HTTP_404_NOT_FOUND, "user_not_found", "User not found.")
        if response.status_code == 409:
            raise api_error(status.HTTP_409_CONFLICT, "user_exists", "This email is already in use.")
        if response.status_code not in (200, 201, 204):
            raise api_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "user_directory_unavailable",
                "User management is temporarily unavailable.",
            )
        return response

    def list_users(self, organization_id: uuid.UUID) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            users = self._request(
                "GET", "/users", params={"first": page * PAGE_SIZE, "max": PAGE_SIZE}
            ).json()
            if not isinstance(users, list):
                raise api_error(503, "user_directory_unavailable", "Invalid user directory response.")
            found.extend(u for u in users if self._belongs(u, organization_id))
            if len(users) < PAGE_SIZE:
                return found
        # Never silently hide users: that could break the last-admin protection.
        raise api_error(503, "user_directory_too_large", "The user directory is too large to manage safely.")

    @staticmethod
    def _belongs(user: dict[str, Any], organization_id: uuid.UUID) -> bool:
        attrs = user.get("attributes") or {}
        ids = attrs.get("organization_id") if isinstance(attrs, dict) else None
        if not isinstance(ids, list) or len(ids) != 1:
            return False
        try:
            return uuid.UUID(ids[0]) == organization_id
        except (ValueError, TypeError, AttributeError):
            return False

    def get_user(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> dict[str, Any]:
        user = self._request("GET", f"/users/{user_id}").json()
        if not self._belongs(user, organization_id):
            # Never reveal whether a user exists in another organisation.
            raise api_error(404, "user_not_found", "User not found.")
        return user

    def assigned_roles(self, user_id: str) -> set[str]:
        roles = self._request("GET", f"/users/{user_id}/role-mappings/realm").json()
        return {r["name"] for r in roles if isinstance(r, dict) and isinstance(r.get("name"), str)}

    def _role(self, role: str) -> dict[str, Any]:
        if role not in MANAGED_ROLES:
            raise api_error(422, "invalid_role", "Unsupported role.", "role")
        # If imported Keycloak did not have these roles, fail closed. Do not assign arbitrary roles.
        try:
            return self._request("GET", f"/roles/{role}").json()
        except Exception as exc:
            if getattr(exc, "status_code", None) == 404:
                raise api_error(503, "role_not_configured", "Configure the organisation roles in Keycloak first.") from exc
            raise

    def update_role(self, user_id: str, role: str) -> None:
        desired = self._role(role)
        assigned = self.assigned_roles(user_id) & MANAGED_ROLES
        if role not in assigned:
            self._request("POST", f"/users/{user_id}/role-mappings/realm", json=[desired])
        for old in assigned - {role}:
            previous = self._role(old)
            self._request("DELETE", f"/users/{user_id}/role-mappings/realm", json=[previous])
        self._request("POST", f"/users/{user_id}/logout")

    def invite(self, email: str, name: str, organization_id: uuid.UUID, role: str) -> dict[str, Any]:
        # Resolve the selected role before creating anything.
        selected = self._role(role)
        parts = name.strip().split(maxsplit=1)
        payload = {
            "username": email,
            "email": email,
            "emailVerified": False,
            "enabled": True,
            "firstName": parts[0] if parts else "",
            "lastName": parts[1] if len(parts) > 1 else "",
            "requiredActions": ["VERIFY_EMAIL", "UPDATE_PASSWORD"],
            "attributes": {"organization_id": [str(organization_id)]},
        }
        created = self._request("POST", "/users", json=payload)
        location = created.headers.get("Location", "")
        user_id = location.rstrip("/").split("/")[-1]
        try:
            uuid.UUID(user_id)
        except ValueError as exc:
            raise api_error(503, "user_directory_unavailable", "Could not identify the invited user.") from exc
        try:
            self._request("POST", f"/users/{user_id}/role-mappings/realm", json=[selected])
            self.send_invitation(user_id)
            return self._request("GET", f"/users/{user_id}").json()
        except Exception:
            # A failed e-mail or role assignment should not leave a half-created account.
            self._request("DELETE", f"/users/{user_id}")
            raise

    def send_invitation(self, user_id: str) -> None:
        self._request(
            "PUT", f"/users/{user_id}/execute-actions-email",
            params={
                "client_id": "bizpartnercheck-web",
                "redirect_uri": self._client.app_url,
                "lifespan": INVITE_LIFETIME,
            },
            json=["VERIFY_EMAIL", "UPDATE_PASSWORD"],
        )

    def set_enabled(self, user_id: str, enabled: bool) -> None:
        self._request("PUT", f"/users/{user_id}", json={"enabled": enabled})
        if not enabled:
            self._request("POST", f"/users/{user_id}/logout")

    def delete(self, user_id: str) -> None:
        self._request("DELETE", f"/users/{user_id}")


def get_directory() -> Iterator[KeycloakDirectory]:
    directory = KeycloakDirectory()
    try:
        yield directory
    finally:
        directory.close()


Directory = Annotated[KeycloakDirectory, Depends(get_directory)]
