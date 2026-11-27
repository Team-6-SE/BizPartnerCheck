"""SCRUM-49: organisation admin invitations, role changes and user lifecycle."""

import re
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, OrgAdmin
from app.db.session import get_db
from app.errors import api_error
from app.tenancy import get_current_organization_id
from app.users.directory import Directory, KeycloakDirectory, MANAGED_ROLES

router = APIRouter(prefix="/users", tags=["user management"])
OrganizationId = Annotated[uuid.UUID, Depends(get_current_organization_id)]
DbSession = Annotated[Session, Depends(get_db)]
Role = Literal["org-admin", "checker", "reviewer"]


class InviteUser(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=255)
    role: Role


class ChangeRole(BaseModel):
    role: Role


class ChangeStatus(BaseModel):
    enabled: bool


def _scoped_lock(db: Session, organization_id: uuid.UUID) -> None:
    """Serialise last-admin operations across server workers for this organisation."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:org, 0))"),
        {"org": str(organization_id)},
    )


def _current_role(directory: KeycloakDirectory, user_id: str) -> str | None:
    roles = directory.assigned_roles(user_id) & MANAGED_ROLES
    return next((r for r in ("org-admin", "checker", "reviewer") if r in roles), None)


def _present(directory: KeycloakDirectory, user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user.get("email") or user.get("username"),
        "name": " ".join(filter(None, [user.get("firstName"), user.get("lastName")])),
        "role": _current_role(directory, user["id"]),
        "enabled": bool(user.get("enabled")),
        "email_verified": bool(user.get("emailVerified")),
    }


def _ensure_other_admin(directory: KeycloakDirectory, organization_id: uuid.UUID, target_id: str) -> None:
    other_admins = [
        u for u in directory.list_users(organization_id)
        if u["id"] != target_id
        and u.get("enabled")
        and u.get("emailVerified")
        and "org-admin" in directory.assigned_roles(u["id"])
    ]
    if not other_admins:
        raise api_error(
            status.HTTP_409_CONFLICT,
            "last_admin",
            "The last active organisation admin cannot be removed or demoted.",
        )


def _verify_active_admin(admin: CurrentUser, directory: KeycloakDirectory, organization_id: uuid.UUID) -> None:
    """Recheck permissions against Keycloak so removed/disabled admins cannot reuse old JWTs."""
    try:
        admin_id = uuid.UUID(admin.id)
        profile = directory.get_user(admin_id, organization_id)
    except (ValueError, TypeError) as exc:
        raise api_error(403, "forbidden", "Only active organisation admins can manage users.") from exc
    except Exception as exc:
        if getattr(exc, "status_code", None) == 404:
            raise api_error(403, "forbidden", "Only active organisation admins can manage users.") from exc
        raise
    if not profile.get("enabled") or "org-admin" not in directory.assigned_roles(admin.id):
        raise api_error(403, "forbidden", "Only active organisation admins can manage users.")


@router.get("")
def list_users(_admin: OrgAdmin, directory: Directory, organization_id: OrganizationId) -> list[dict[str, Any]]:
    _verify_active_admin(_admin, directory, organization_id)
    return [_present(directory, u) for u in directory.list_users(organization_id)]


@router.post("/invitations", status_code=status.HTTP_201_CREATED)
def invite_user(body: InviteUser, _admin: OrgAdmin, directory: Directory, organization_id: OrganizationId) -> dict[str, Any]:
    _verify_active_admin(_admin, directory, organization_id)
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise api_error(422, "invalid_email", "Enter a valid email address.", "email")
    name = body.name.strip()
    if not name:
        raise api_error(422, "invalid_name", "Name is required.", "name")
    created = directory.invite(email, name, organization_id, body.role)
    return _present(directory, created)


@router.post("/{user_id}/resend-invitation")
def resend_invitation(user_id: uuid.UUID, _admin: OrgAdmin, directory: Directory, organization_id: OrganizationId) -> dict[str, str]:
    _verify_active_admin(_admin, directory, organization_id)
    user = directory.get_user(user_id, organization_id)
    if user.get("emailVerified"):
        raise api_error(409, "already_verified", "This user has already verified their email.")
    directory.send_invitation(user["id"])
    return {"message": "Invitation sent."}


@router.patch("/{user_id}/role")
def change_role(
    user_id: uuid.UUID, body: ChangeRole, _admin: OrgAdmin, directory: Directory,
    organization_id: OrganizationId, db: DbSession,
) -> dict[str, Any]:
    _scoped_lock(db, organization_id)
    try:
        _verify_active_admin(_admin, directory, organization_id)
        user = directory.get_user(user_id, organization_id)
        old = _current_role(directory, user["id"])
        if old == "org-admin" and body.role != "org-admin" and user.get("enabled"):
            _ensure_other_admin(directory, organization_id, user["id"])
        directory.update_role(user["id"], body.role)
        return _present(directory, directory.get_user(user_id, organization_id))
    finally:
        db.commit()


@router.patch("/{user_id}/status")
def change_status(
    user_id: uuid.UUID, body: ChangeStatus, _admin: OrgAdmin, directory: Directory,
    organization_id: OrganizationId, db: DbSession,
) -> dict[str, Any]:
    _scoped_lock(db, organization_id)
    try:
        _verify_active_admin(_admin, directory, organization_id)
        user = directory.get_user(user_id, organization_id)
        if not body.enabled and user.get("enabled") and _current_role(directory, user["id"]) == "org-admin":
            _ensure_other_admin(directory, organization_id, user["id"])
        directory.set_enabled(user["id"], body.enabled)
        return _present(directory, directory.get_user(user_id, organization_id))
    finally:
        db.commit()


@router.delete("/{user_id}")
def delete_user(
    user_id: uuid.UUID, _admin: OrgAdmin, directory: Directory,
    organization_id: OrganizationId, db: DbSession,
) -> dict[str, str]:
    _scoped_lock(db, organization_id)
    try:
        _verify_active_admin(_admin, directory, organization_id)
        user = directory.get_user(user_id, organization_id)
        if user.get("enabled") and _current_role(directory, user["id"]) == "org-admin":
            _ensure_other_admin(directory, organization_id, user["id"])
        directory.delete(user["id"])
        return {"message": "User removed."}
    finally:
        db.commit()
