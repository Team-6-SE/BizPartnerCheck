"""The security log: who signed in, failed to sign in, changed users or roles, created or
revoked API tokens, exported data, and when.

Two sources write into the same append-only table `security_events`:

- Keycloak (sign-ins, passwords, second factor, user and role changes), copied by
  app/security/keycloak.py
- this app (API tokens, exports), through `record_event()`

Details: docs/security-log.md
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db.models import SecurityEvent


class EventType(StrEnum):
    SIGN_IN = "SIGN_IN"
    SIGN_IN_FAILED = "SIGN_IN_FAILED"
    SIGN_OUT = "SIGN_OUT"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"
    MFA_ENABLED = "MFA_ENABLED"
    MFA_REMOVED = "MFA_REMOVED"
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    USER_DELETED = "USER_DELETED"
    ROLE_ASSIGNED = "ROLE_ASSIGNED"
    ROLE_REMOVED = "ROLE_REMOVED"
    API_TOKEN_CREATED = "API_TOKEN_CREATED"
    API_TOKEN_REVOKED = "API_TOKEN_REVOKED"
    DATA_EXPORTED = "DATA_EXPORTED"


SOURCE_APP = "app"
SOURCE_KEYCLOAK = "keycloak"


def record_event(
    db: Session,
    *,
    organization_id: uuid.UUID | None,
    event_type: EventType,
    actor: CurrentUser | None,
    summary: str,
    subject_id: str | None = None,
    subject_email: str | None = None,
    ip_address: str | None = None,
    details: dict[str, Any] | None = None,
) -> SecurityEvent:
    """Add an event caused by this app (e.g. API token created, data exported).

    The caller commits; the event is part of the same transaction as the action itself,
    so an action that is rolled back leaves no log entry, and the other way round.
    """
    event = SecurityEvent(
        organization_id=organization_id,
        occurred_at=datetime.now(UTC),
        event_type=event_type.value,
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        subject_id=subject_id,
        subject_email=subject_email,
        ip_address=ip_address,
        source=SOURCE_APP,
        details={"summary": summary, **(details or {})},
    )
    db.add(event)
    return event
