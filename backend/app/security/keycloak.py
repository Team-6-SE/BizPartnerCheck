"""Copy Keycloak's sign-in events and admin events into our security log.

Keycloak records the events itself (realm settings in infra/keycloak/import). The API reads
them with its own service account (client "bizpartnercheck-api", may only read events and
users) and stores them in `security_events`, where they are kept independent of Keycloak's
own expiry. Copying happens before the log is shown and every few minutes in the background;
each Keycloak event is stored once, however often we copy (unique external ID).

Details: docs/security-log.md
"""

import json
import os
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import httpx2 as httpx
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth import DEFAULT_ISSUER
from app.db.models import SecurityEvent
from app.security.events import SOURCE_KEYCLOAK, EventType
from app.tenancy import TEST_ORGANIZATION_ID

DEFAULT_CLIENT_ID = "bizpartnercheck-api"
# Only valid for the local development Keycloak (infra/keycloak/import). Never used with
# any other OIDC_ISSUER: there KEYCLOAK_API_CLIENT_SECRET must be set.
LOCAL_DEV_SECRET = "local-dev-only-change-in-production"

PAGE_SIZE = 100
MAX_PAGES = 20  # at most 2,000 events per kind and sync; the rest comes next time
EMAIL_CACHE_SIZE = 1_000
# Events may arrive a little late, so each run looks back a bit; duplicates are skipped.
OVERLAP = timedelta(minutes=2)


# Only what the log shows is fetched (see map_user_event / map_admin_event).
USER_EVENT_TYPES = [
    "LOGIN",
    "LOGIN_ERROR",
    "LOGOUT",
    "UPDATE_CREDENTIAL",
    "REMOVE_CREDENTIAL",
    "SEND_RESET_PASSWORD",
    "USER_DISABLED_BY_TEMPORARY_LOCKOUT",
    "USER_DISABLED_BY_PERMANENT_LOCKOUT",
]
ADMIN_RESOURCE_TYPES = ["USER", "REALM_ROLE_MAPPING", "CLIENT_ROLE_MAPPING"]


class KeycloakUnavailable(Exception):
    """Keycloak could not be asked (down, wrong secret, missing permission)."""


# ------------------------------------------------------------------ Keycloak access


class KeycloakAdminClient:
    """Reads events and users through Keycloak's admin REST API (read-only permissions)."""

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        base_url = base_url.rstrip("/")
        self.token_url = f"{base_url}/protocol/openid-connect/token"
        self.admin_url = base_url.replace("/realms/", "/admin/realms/", 1)
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = httpx.Client(transport=transport, timeout=timeout)
        self._clock = clock
        self._token: str | None = None
        self._token_valid_until = 0.0
        self._emails: dict[str, str | None] = {}

    def events(
        self, date_from_ms: int, first: int, max_results: int
    ) -> list[dict[str, Any]]:
        return self._get(
            "/events",
            {**_page(date_from_ms, first, max_results), "type": USER_EVENT_TYPES},
        )

    def admin_events(
        self, date_from_ms: int, first: int, max_results: int
    ) -> list[dict[str, Any]]:
        return self._get(
            "/admin-events",
            {
                **_page(date_from_ms, first, max_results),
                "resourceTypes": ADMIN_RESOURCE_TYPES,
            },
        )

    def user_email(self, user_id: str) -> str | None:
        """E-mail of a Keycloak user; None if the user no longer exists."""
        if len(self._emails) > EMAIL_CACHE_SIZE:
            self._emails.clear()  # small and fresh: e-mails can change
        if user_id not in self._emails:
            try:
                user = self._get(f"/users/{user_id}", {})
            except _NotFound:
                user = {}
            self._emails[user_id] = user.get("email") or user.get("username")
        return self._emails[user_id]

    # -------------------------------------------------------------- internals

    def _access_token(self) -> str:
        if self._token and self._clock() < self._token_valid_until:
            return self._token
        try:
            response = self._http.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        except httpx.HTTPError as exc:
            raise KeycloakUnavailable("Keycloak is not reachable.") from exc
        if response.status_code != 200:
            raise KeycloakUnavailable(
                f"Keycloak refused the API's service account (HTTP {response.status_code})."
            )
        body = response.json()
        self._token = body["access_token"]
        # Renew 30 s before it expires.
        self._token_valid_until = self._clock() + max(
            0, int(body.get("expires_in", 60)) - 30
        )
        return self._token

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        for attempt in range(2):
            try:
                response = self._http.get(
                    f"{self.admin_url}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._access_token()}"},
                )
            except httpx.HTTPError as exc:
                raise KeycloakUnavailable("Keycloak is not reachable.") from exc
            if response.status_code == 401:
                if attempt == 0:
                    self._token = None  # expired or revoked: get a new one once
                    continue
                raise KeycloakUnavailable("Keycloak did not accept the API's token.")
            if response.status_code == 404:
                raise _NotFound()
            if response.status_code != 200:
                raise KeycloakUnavailable(
                    f"Keycloak did not return the events (HTTP {response.status_code})."
                )
            return response.json()
        raise AssertionError("unreachable")


class _NotFound(Exception):
    pass


def _page(date_from_ms: int, first: int, max_results: int) -> dict[str, Any]:
    # Oldest first: events added while we read land behind the page we are on, and the
    # next sync continues where this one stopped (also after MAX_PAGES).
    return {
        "dateFrom": date_from_ms,
        "first": first,
        "max": max_results,
        "direction": "asc",
    }


@lru_cache
def get_keycloak_client() -> KeycloakAdminClient | None:
    """FastAPI dependency: the Keycloak reader, or None when it is not configured."""
    issuer = os.environ.get("OIDC_ISSUER") or DEFAULT_ISSUER
    base_url = os.environ.get("KEYCLOAK_API_BASE_URL") or issuer
    secret = os.environ.get("KEYCLOAK_API_CLIENT_SECRET")
    if not secret and issuer == DEFAULT_ISSUER:
        secret = LOCAL_DEV_SECRET
    if not secret:
        return None
    client_id = os.environ.get("KEYCLOAK_API_CLIENT_ID") or DEFAULT_CLIENT_ID
    return KeycloakAdminClient(base_url, client_id, secret)


# ------------------------------------------------------------------ mapping


@dataclass
class MappedEvent:
    external_id: str
    occurred_at: datetime
    event_type: EventType
    actor_id: str | None = None
    actor_email: str | None = None
    subject_id: str | None = None
    subject_email: str | None = None
    ip_address: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    # Filled in by the sync, with e-mails looked up in Keycloak where needed.
    summary: str = ""


FAILURE_REASONS = {
    "invalid_user_credentials": "wrong password or one-time code",
    "user_not_found": "unknown e-mail address",
    "user_temporarily_disabled": "account temporarily locked",
    "user_disabled": "account disabled",
    "expired_code": "sign-in took too long",
    "invalid_code": "sign-in link no longer valid",
}


def _time(ms: Any) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=UTC)


def map_user_event(event: dict[str, Any]) -> MappedEvent | None:
    """A Keycloak user event (sign-in, password, second factor, …) or None if not logged."""
    kind = event.get("type")
    details = event.get("details") or {}
    credential = details.get("credential_type")

    event_type: EventType | None = None
    extra: dict[str, Any] = {}
    if kind == "LOGIN":
        event_type = EventType.SIGN_IN
        # Setting up the app: credential_type "otp". Signing in with it: Keycloak names
        # the authenticator used (selected_credential_id); a password-only sign-in does not.
        extra["second_factor"] = credential == "otp" or bool(
            details.get("selected_credential_id")
        )
    elif kind == "LOGIN_ERROR":
        event_type = EventType.SIGN_IN_FAILED
        extra["reason"] = event.get("error")
    elif kind == "LOGOUT":
        event_type = EventType.SIGN_OUT
    elif kind in (
        "USER_DISABLED_BY_TEMPORARY_LOCKOUT",
        "USER_DISABLED_BY_PERMANENT_LOCKOUT",
    ):
        event_type = EventType.ACCOUNT_LOCKED
        extra["permanent"] = kind == "USER_DISABLED_BY_PERMANENT_LOCKOUT"
    elif kind == "UPDATE_CREDENTIAL":
        event_type = (
            EventType.PASSWORD_CHANGED
            if credential == "password"
            else EventType.MFA_ENABLED
        )
        extra["credential_type"] = credential
    elif kind == "REMOVE_CREDENTIAL":
        if credential == "password":
            return None
        event_type = EventType.MFA_REMOVED
        extra["credential_type"] = credential
    elif kind == "SEND_RESET_PASSWORD":
        event_type = EventType.PASSWORD_RESET_REQUESTED
    if event_type is None or not event.get("id") or event.get("time") is None:
        return None

    user_id = event.get("userId")
    email = details.get("username")
    return MappedEvent(
        external_id=f"event:{event['id']}",
        occurred_at=_time(event["time"]),
        event_type=event_type,
        actor_id=user_id,
        actor_email=email,
        subject_id=user_id,
        subject_email=email,
        ip_address=event.get("ipAddress"),
        details={"client": event.get("clientId"), **extra},
    )


def _json_list_or_dict(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return None


def map_admin_event(event: dict[str, Any]) -> MappedEvent | None:
    """A Keycloak admin event (user or role change) or None if not logged."""
    resource = event.get("resourceType")
    operation = event.get("operationType")
    path = event.get("resourcePath") or ""
    if (
        not event.get("id")
        or event.get("time") is None
        or not path.startswith("users/")
    ):
        return None
    parts = path.split("/")  # users/{id}[/sub-resource/...]
    subject_id = parts[1]
    sub_resource = parts[2] if len(parts) > 2 else None
    representation = _json_list_or_dict(event.get("representation"))
    extra: dict[str, Any] = {}

    event_type: EventType | None = None
    if resource == "USER" and sub_resource is None:
        if operation == "CREATE":
            event_type = EventType.USER_CREATED
        elif operation == "DELETE":
            event_type = EventType.USER_DELETED
        elif operation == "UPDATE":
            event_type = EventType.USER_UPDATED
            # Keycloak stores the whole request (all fields), not only what changed.
            if (
                isinstance(representation, dict)
                and representation.get("enabled") is False
            ):
                extra["disabled"] = True
    elif resource == "USER" and operation == "ACTION":
        if sub_resource == "reset-password":
            event_type = EventType.PASSWORD_CHANGED
            extra["by_admin"] = True
        elif sub_resource == "credentials":
            # Usually an authenticator app of someone who lost the phone. Keycloak does
            # not say which kind of credential it was.
            event_type = EventType.MFA_REMOVED
            extra["by_admin"] = True
        elif sub_resource == "logout":
            event_type = EventType.SIGN_OUT
            extra["by_admin"] = True
    elif resource in ("REALM_ROLE_MAPPING", "CLIENT_ROLE_MAPPING") and operation in (
        "CREATE",
        "DELETE",
    ):
        event_type = (
            EventType.ROLE_ASSIGNED if operation == "CREATE" else EventType.ROLE_REMOVED
        )
        roles = representation if isinstance(representation, list) else []
        extra["roles"] = sorted(
            r["name"] for r in roles if isinstance(r, dict) and "name" in r
        )
    if event_type is None:
        return None

    subject_email = None
    if isinstance(representation, dict) and resource == "USER":
        subject_email = representation.get("email") or representation.get("username")

    auth = event.get("authDetails") or {}
    same_realm = auth.get("realmId") == event.get("realmId")
    return MappedEvent(
        external_id=f"admin:{event['id']}",
        occurred_at=_time(event["time"]),
        event_type=event_type,
        # An admin of Keycloak's master realm is not a user of our realm.
        actor_id=auth.get("userId") if same_realm else None,
        subject_id=subject_id,
        subject_email=subject_email,
        ip_address=auth.get("ipAddress"),
        details={"keycloak_admin": not same_realm, **extra},
    )


def describe(event: MappedEvent) -> str:
    """One sentence for the log (also used in the CSV export)."""
    d = event.details
    who = event.subject_email or "a user"
    by = " by a Keycloak administrator" if d.get("keycloak_admin") else ""
    match event.event_type:
        case EventType.SIGN_IN:
            return (
                "Signed in with password and one-time code"
                if d.get("second_factor")
                else "Signed in with password"
            )
        case EventType.SIGN_IN_FAILED:
            reason = FAILURE_REASONS.get(
                d.get("reason") or "", d.get("reason") or "unknown reason"
            )
            return f"Sign-in failed: {reason}"
        case EventType.SIGN_OUT:
            if d.get("by_admin"):
                return f"{who} signed out of all sessions{by}"
            return "Signed out"
        case EventType.ACCOUNT_LOCKED:
            return "Account locked after too many failed sign-ins" + (
                " (permanently)" if d.get("permanent") else ""
            )
        case EventType.PASSWORD_CHANGED:
            return (
                f"Password of {who} set{by}"
                if d.get("by_admin")
                else "Password changed"
            )
        case EventType.PASSWORD_RESET_REQUESTED:
            return "Password reset e-mail requested"
        case EventType.MFA_ENABLED:
            return (
                "Authenticator app set up"
                if d.get("credential_type") == "otp"
                else "Second factor set up"
            )
        case EventType.MFA_REMOVED if d.get("by_admin"):
            return f"Sign-in method of {who} removed (e.g. authenticator app){by}"
        case EventType.MFA_REMOVED:
            return (
                "Authenticator app removed"
                if d.get("credential_type") == "otp"
                else "Second factor removed"
            )
        case EventType.USER_CREATED:
            return f"User {who} created{by}"
        case EventType.USER_UPDATED:
            if d.get("disabled"):
                return f"User {who} changed (account disabled){by}"
            return f"User {who} changed{by}"
        case EventType.USER_DELETED:
            return f"User {who} deleted{by}"
        case EventType.ROLE_ASSIGNED:
            return f"Role {', '.join(d.get('roles') or ['?'])} given to {who}{by}"
        case EventType.ROLE_REMOVED:
            return f"Role {', '.join(d.get('roles') or ['?'])} taken from {who}{by}"
        case _:
            return event.event_type.value


def organization_for_user(user_id: str | None) -> uuid.UUID | None:
    """The customer organisation of a Keycloak user.

    Until story S2.3 puts the organisation into Keycloak, every known user belongs to the
    test organisation. Events without a user (e.g. a failed sign-in with an unknown
    e-mail) belong to no organisation and are not shown to organisation admins.
    """
    return TEST_ORGANIZATION_ID if user_id else None


# ------------------------------------------------------------------ sync


@dataclass
class SyncResult:
    imported: int = 0
    error: str | None = None


def _cursor_ms(db: Session, prefix: str) -> int:
    latest = db.scalar(
        select(func.max(SecurityEvent.occurred_at)).where(
            SecurityEvent.source == SOURCE_KEYCLOAK,
            SecurityEvent.external_id.like(f"{prefix}:%"),
        )
    )
    if latest is None:
        return 0
    return int((latest - OVERLAP).timestamp() * 1000)


def _cut(value: str | None, length: int) -> str | None:
    """Values from Keycloak may be longer than our columns (e.g. a typed-in user name
    of a failed sign-in); one such value must not stop all further copying."""
    return value[:length] if value else value


def _rows(
    client: KeycloakAdminClient, events: Iterable[MappedEvent]
) -> list[dict[str, Any]]:
    rows = []
    for event in events:
        if event.subject_id and not event.subject_email:
            event.subject_email = client.user_email(event.subject_id)
        if event.actor_id and not event.actor_email:
            event.actor_email = client.user_email(event.actor_id)
        event.summary = describe(event)
        # Admin events: the organisation of the changed user.
        owner = event.subject_id or event.actor_id
        rows.append(
            {
                "id": uuid.uuid4(),
                "organization_id": organization_for_user(owner),
                "occurred_at": event.occurred_at,
                "event_type": event.event_type.value,
                "actor_id": _cut(event.actor_id, 64),
                "actor_email": _cut(event.actor_email, 320),
                "subject_id": _cut(event.subject_id, 64),
                "subject_email": _cut(event.subject_email, 320),
                "ip_address": _cut(event.ip_address, 64),
                "source": SOURCE_KEYCLOAK,
                "external_id": event.external_id,
                "details": {"summary": event.summary, **event.details},
            }
        )
    return rows


def _insert(db: Session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    statement = (
        insert(SecurityEvent)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["source", "external_id"],
            index_where=text("external_id IS NOT NULL"),
        )
        .returning(SecurityEvent.id)  # only the rows really added (not the duplicates)
    )
    return len(db.execute(statement).all())


def sync_keycloak_events(db: Session, client: KeycloakAdminClient) -> SyncResult:
    """Copy new Keycloak events into the security log. Never raises for Keycloak problems.

    What was copied before a problem is kept (the next sync continues from there).
    """
    streams = (
        ("event", client.events, map_user_event),
        ("admin", client.admin_events, map_admin_event),
    )
    result = SyncResult()
    try:
        for prefix, fetch, mapper in streams:
            since = _cursor_ms(db, prefix)
            for page in range(MAX_PAGES):
                batch = fetch(since, page * PAGE_SIZE, PAGE_SIZE)
                mapped = [m for m in (mapper(raw) for raw in batch) if m is not None]
                result.imported += _insert(db, _rows(client, mapped))
                if len(batch) < PAGE_SIZE:
                    break
    except KeycloakUnavailable as exc:
        result.error = str(exc)
    db.commit()
    return result
