"""Story S2.6: security log (Keycloak events copied in, app events, admin-only API)."""

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db.models import Organization, SecurityEvent
from app.main import app
from app.security.events import SOURCE_APP, SOURCE_KEYCLOAK, EventType, record_event
from app.security.keycloak import (
    OVERLAP,
    KeycloakAdminClient,
    KeycloakUnavailable,
    describe,
    get_keycloak_client,
    map_admin_event,
    map_user_event,
    sync_keycloak_events,
)
from app.tenancy import TEST_ORGANIZATION_ID

REALM_ID = "realm-bpc"
NOW_MS = int(datetime(2026, 11, 5, 10, 0, tzinfo=UTC).timestamp() * 1000)


def user_event(
    type_: str,
    *,
    id_: str | None = None,
    time: int = NOW_MS,
    user_id: str | None = "user-1",
    username: str | None = "anna@example.com",
    **details: Any,
) -> dict[str, Any]:
    return {
        "id": id_ or str(uuid.uuid4()),
        "time": time,
        "type": type_,
        "realmId": REALM_ID,
        "clientId": "bizpartnercheck-web",
        "userId": user_id,
        "ipAddress": "203.0.113.7",
        "details": {"username": username, **details} if username else details,
    }


def admin_event(
    resource: str,
    operation: str,
    path: str,
    representation: Any = None,
    *,
    time: int = NOW_MS,
    admin_realm: str = REALM_ID,
    admin_id: str = "admin-1",
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "time": time,
        "realmId": REALM_ID,
        "authDetails": {
            "realmId": admin_realm,
            "clientId": "admin-cli",
            "userId": admin_id,
            "ipAddress": "198.51.100.4",
        },
        "operationType": operation,
        "resourceType": resource,
        "resourcePath": path,
        "representation": None
        if representation is None
        else json.dumps(representation),
    }


# ------------------------------------------------------------------ mapping


def test_sign_in_with_second_factor() -> None:
    mapped = map_user_event(user_event("LOGIN", credential_type="otp"))

    assert mapped is not None
    assert mapped.event_type == EventType.SIGN_IN
    assert mapped.actor_email == "anna@example.com"
    assert mapped.ip_address == "203.0.113.7"
    assert mapped.occurred_at == datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    assert describe(mapped) == "Signed in with password and one-time code"


def test_sign_in_with_existing_authenticator() -> None:
    # A normal sign-in with the app: Keycloak only names the credential it used.
    mapped = map_user_event(user_event("LOGIN", selected_credential_id="cred-1"))

    assert mapped is not None
    assert describe(mapped) == "Signed in with password and one-time code"


def test_sign_in_with_password_only() -> None:
    mapped = map_user_event(user_event("LOGIN"))

    assert mapped is not None
    assert describe(mapped) == "Signed in with password"


def test_failed_sign_in_says_why() -> None:
    raw = user_event("LOGIN_ERROR", auth_method="openid-connect")
    raw["error"] = "invalid_user_credentials"

    mapped = map_user_event(raw)

    assert mapped is not None
    assert mapped.event_type == EventType.SIGN_IN_FAILED
    assert describe(mapped) == "Sign-in failed: wrong password or one-time code"


def test_failed_sign_in_with_unknown_reason_keeps_keycloak_code() -> None:
    raw = user_event("LOGIN_ERROR")
    raw["error"] = "something_new"

    mapped = map_user_event(raw)

    assert mapped is not None
    assert describe(mapped) == "Sign-in failed: something_new"


@pytest.mark.parametrize(
    ("raw", "event_type", "summary"),
    [
        (user_event("LOGOUT"), EventType.SIGN_OUT, "Signed out"),
        (
            user_event("UPDATE_CREDENTIAL", credential_type="password"),
            EventType.PASSWORD_CHANGED,
            "Password changed",
        ),
        (
            user_event("UPDATE_CREDENTIAL", credential_type="otp"),
            EventType.MFA_ENABLED,
            "Authenticator app set up",
        ),
        (
            user_event("REMOVE_CREDENTIAL", credential_type="otp"),
            EventType.MFA_REMOVED,
            "Authenticator app removed",
        ),
        (
            user_event("SEND_RESET_PASSWORD"),
            EventType.PASSWORD_RESET_REQUESTED,
            "Password reset e-mail requested",
        ),
        (
            user_event("USER_DISABLED_BY_TEMPORARY_LOCKOUT"),
            EventType.ACCOUNT_LOCKED,
            "Account locked after too many failed sign-ins",
        ),
        (
            user_event("USER_DISABLED_BY_PERMANENT_LOCKOUT"),
            EventType.ACCOUNT_LOCKED,
            "Account locked after too many failed sign-ins (permanently)",
        ),
    ],
)
def test_user_events(raw: dict[str, Any], event_type: EventType, summary: str) -> None:
    mapped = map_user_event(raw)

    assert mapped is not None
    assert mapped.event_type == event_type
    assert describe(mapped) == summary


@pytest.mark.parametrize(
    "raw",
    [
        user_event("CODE_TO_TOKEN"),
        user_event("REFRESH_TOKEN"),
        user_event("REMOVE_CREDENTIAL", credential_type="password"),
        {**user_event("LOGIN"), "id": None},
        {**user_event("LOGIN"), "time": None},
    ],
)
def test_other_user_events_are_not_logged(raw: dict[str, Any]) -> None:
    assert map_user_event(raw) is None


def test_user_created_by_admin() -> None:
    mapped = map_admin_event(
        admin_event(
            "USER",
            "CREATE",
            "users/u-2",
            {"username": "ben@example.com", "email": "ben@example.com"},
        )
    )

    assert mapped is not None
    assert mapped.event_type == EventType.USER_CREATED
    assert mapped.actor_id == "admin-1"
    assert mapped.subject_id == "u-2"
    assert mapped.subject_email == "ben@example.com"
    assert describe(mapped) == "User ben@example.com created"


def test_user_updated() -> None:
    mapped = map_admin_event(
        admin_event(
            "USER",
            "UPDATE",
            "users/u-2",
            {"id": "u-2", "enabled": True, "email": "ben@example.com"},
        )
    )

    assert mapped is not None
    assert mapped.event_type == EventType.USER_UPDATED
    assert describe(mapped) == "User ben@example.com changed"


def test_user_disabled() -> None:
    mapped = map_admin_event(
        admin_event(
            "USER",
            "UPDATE",
            "users/u-2",
            {"enabled": False, "email": "ben@example.com"},
        )
    )

    assert mapped is not None
    assert describe(mapped) == "User ben@example.com changed (account disabled)"


def test_admin_removes_authenticator() -> None:
    mapped = map_admin_event(admin_event("USER", "ACTION", "users/u-2/credentials/c-9"))

    assert mapped is not None
    assert mapped.event_type == EventType.MFA_REMOVED
    mapped.subject_email = "ben@example.com"
    assert (
        describe(mapped)
        == "Sign-in method of ben@example.com removed (e.g. authenticator app)"
    )


def test_admin_signs_user_out_everywhere() -> None:
    mapped = map_admin_event(admin_event("USER", "ACTION", "users/u-2/logout"))

    assert mapped is not None
    assert mapped.event_type == EventType.SIGN_OUT
    mapped.subject_email = "ben@example.com"
    assert describe(mapped) == "ben@example.com signed out of all sessions"


def test_role_given() -> None:
    mapped = map_admin_event(
        admin_event(
            "REALM_ROLE_MAPPING",
            "CREATE",
            "users/u-2/role-mappings/realm",
            [{"id": "r1", "name": "org-admin"}],
        )
    )

    assert mapped is not None
    assert mapped.event_type == EventType.ROLE_ASSIGNED
    mapped.subject_email = "ben@example.com"
    assert describe(mapped) == "Role org-admin given to ben@example.com"


def test_role_taken_away() -> None:
    mapped = map_admin_event(
        admin_event(
            "CLIENT_ROLE_MAPPING",
            "DELETE",
            "users/u-2/role-mappings/clients/c1",
            [{"name": "view-events"}],
        )
    )

    assert mapped is not None
    assert mapped.event_type == EventType.ROLE_REMOVED
    assert mapped.details["roles"] == ["view-events"]


def test_password_set_by_admin() -> None:
    mapped = map_admin_event(admin_event("USER", "ACTION", "users/u-2/reset-password"))

    assert mapped is not None
    assert mapped.event_type == EventType.PASSWORD_CHANGED
    mapped.subject_email = "ben@example.com"
    assert describe(mapped) == "Password of ben@example.com set"


def test_change_by_keycloak_master_admin_has_no_actor_in_our_realm() -> None:
    mapped = map_admin_event(
        admin_event("USER", "DELETE", "users/u-2", admin_realm="master-realm-id")
    )

    assert mapped is not None
    assert mapped.actor_id is None
    assert describe(mapped) == "User a user deleted by a Keycloak administrator"


@pytest.mark.parametrize(
    "raw",
    [
        admin_event("CLIENT", "UPDATE", "clients/c1"),
        admin_event(
            "REALM_ROLE_MAPPING", "CREATE", "groups/g1/role-mappings/realm", []
        ),
        admin_event("USER", "ACTION", "users/u-2/send-verify-email"),
        admin_event(
            "REALM_ROLE_MAPPING", "UPDATE", "users/u-2/role-mappings/realm", []
        ),
        # Not a user deletion, even though the resource type is USER.
        admin_event("USER", "DELETE", "users/u-2/consents/web"),
        admin_event("USER", "CREATE", "users/u-2/groups/g1"),
        {**admin_event("USER", "CREATE", "users/u-2"), "resourcePath": None},
    ],
)
def test_other_admin_events_are_not_logged(raw: dict[str, Any]) -> None:
    assert map_admin_event(raw) is None


# ------------------------------------------------------------------ sync


class FakeKeycloak:
    """Stands in for KeycloakAdminClient: serves the events like Keycloak (oldest first)."""

    def __init__(self) -> None:
        self.user_events: list[dict[str, Any]] = []
        self.admin_events_: list[dict[str, Any]] = []
        self.emails = {
            "user-1": "anna@example.com",
            "u-2": "ben@example.com",
            "admin-1": "admin@example.com",
        }
        self.calls: list[tuple[str, int, int]] = []
        self.down = False

    def _serve(
        self,
        kind: str,
        events: list[dict[str, Any]],
        date_from_ms: int,
        first: int,
        max_results: int,
    ) -> list[dict[str, Any]]:
        if self.down:
            raise KeycloakUnavailable("Keycloak is not reachable.")
        self.calls.append((kind, date_from_ms, first))
        matching = sorted(
            (e for e in events if e["time"] >= date_from_ms), key=lambda e: e["time"]
        )
        return matching[first : first + max_results]

    def events(
        self, date_from_ms: int, first: int, max_results: int
    ) -> list[dict[str, Any]]:
        return self._serve("event", self.user_events, date_from_ms, first, max_results)

    def admin_events(
        self, date_from_ms: int, first: int, max_results: int
    ) -> list[dict[str, Any]]:
        return self._serve(
            "admin", self.admin_events_, date_from_ms, first, max_results
        )

    def user_email(self, user_id: str) -> str | None:
        return self.emails.get(user_id)


@pytest.fixture
def keycloak() -> FakeKeycloak:
    return FakeKeycloak()


def stored(db: Session) -> list[SecurityEvent]:
    return list(db.scalars(select(SecurityEvent).order_by(SecurityEvent.occurred_at)))


def test_sync_copies_events_once(db: Session, keycloak: FakeKeycloak) -> None:
    keycloak.user_events = [
        user_event("LOGIN"),
        user_event("LOGOUT", time=NOW_MS + 1000),
    ]
    keycloak.admin_events_ = [
        admin_event(
            "REALM_ROLE_MAPPING",
            "CREATE",
            "users/u-2/role-mappings/realm",
            [{"name": "org-admin"}],
        )
    ]

    first = sync_keycloak_events(db, keycloak)  # type: ignore[arg-type]
    second = sync_keycloak_events(db, keycloak)  # type: ignore[arg-type]

    assert first.imported == 3 and first.error is None
    assert second.imported == 0
    rows = stored(db)
    assert len(rows) == 3
    assert {row.source for row in rows} == {SOURCE_KEYCLOAK}
    assert {row.organization_id for row in rows} == {TEST_ORGANIZATION_ID}
    role = next(row for row in rows if row.event_type == EventType.ROLE_ASSIGNED)
    # E-mails missing in the admin event are looked up in Keycloak.
    assert role.subject_email == "ben@example.com"
    assert role.actor_email == "admin@example.com"
    assert role.details["summary"] == "Role org-admin given to ben@example.com"


def test_sync_continues_from_newest_copied_event(
    db: Session, keycloak: FakeKeycloak
) -> None:
    keycloak.user_events = [user_event("LOGIN")]
    sync_keycloak_events(db, keycloak)  # type: ignore[arg-type]
    keycloak.calls.clear()

    sync_keycloak_events(db, keycloak)  # type: ignore[arg-type]

    since = NOW_MS - int(OVERLAP.total_seconds() * 1000)
    assert ("event", since, 0) in keycloak.calls


def test_sync_reads_all_pages(db: Session, keycloak: FakeKeycloak) -> None:
    keycloak.user_events = [user_event("LOGIN", time=NOW_MS + i) for i in range(250)]

    result = sync_keycloak_events(db, keycloak)  # type: ignore[arg-type]

    assert result.imported == 250
    assert [first for kind, _, first in keycloak.calls if kind == "event"] == [
        0,
        100,
        200,
    ]


def test_failed_sign_in_of_unknown_user_belongs_to_no_organisation(
    db: Session, keycloak: FakeKeycloak
) -> None:
    raw = user_event("LOGIN_ERROR", user_id=None, username="nobody@example.com")
    raw["error"] = "user_not_found"
    keycloak.user_events = [raw]

    sync_keycloak_events(db, keycloak)  # type: ignore[arg-type]

    (row,) = stored(db)
    assert row.organization_id is None
    assert row.actor_email == "nobody@example.com"


def test_overlong_values_are_cut_not_fatal(db: Session, keycloak: FakeKeycloak) -> None:
    raw = user_event("LOGIN_ERROR", user_id=None, username="x" * 5000)
    raw["error"] = "user_not_found"
    keycloak.user_events = [raw, user_event("LOGIN", time=NOW_MS + 1)]

    result = sync_keycloak_events(db, keycloak)  # type: ignore[arg-type]

    assert result.imported == 2
    assert len(stored(db)[0].actor_email or "") == 320


def test_keycloak_down_is_reported_not_raised(
    db: Session, keycloak: FakeKeycloak
) -> None:
    keycloak.down = True

    result = sync_keycloak_events(db, keycloak)  # type: ignore[arg-type]

    assert result.imported == 0
    assert result.error == "Keycloak is not reachable."
    assert stored(db) == []


# ------------------------------------------------------------------ Keycloak client


def keycloak_client(handler: Any, clock: Any = None) -> KeycloakAdminClient:
    kwargs = {"clock": clock} if clock else {}
    return KeycloakAdminClient(
        "http://kc.test/realms/bizpartnercheck",
        "bizpartnercheck-api",
        "secret",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_client_asks_admin_api_with_service_account_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t1", "expires_in": 300})
        return httpx.Response(200, json=[])

    client = keycloak_client(handler)
    client.events(123, 0, 100)
    client.admin_events(123, 100, 100)

    token_calls = [r for r in seen if r.url.path.endswith("/token")]
    assert len(token_calls) == 1  # token is reused
    assert b"grant_type=client_credentials" in token_calls[0].content
    events_call = seen[1]
    assert events_call.url.path == "/admin/realms/bizpartnercheck/events"
    assert events_call.headers["Authorization"] == "Bearer t1"
    assert events_call.url.params["dateFrom"] == "123"
    assert events_call.url.params["direction"] == "asc"
    assert "LOGIN" in events_call.url.params.get_list("type")
    assert seen[2].url.params.get_list("resourceTypes") == [
        "USER",
        "REALM_ROLE_MAPPING",
        "CLIENT_ROLE_MAPPING",
    ]


def test_client_gets_new_token_after_401_once() -> None:
    tokens = iter(["old", "new"])
    answers = iter([401, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200, json={"access_token": next(tokens), "expires_in": 300}
            )
        return httpx.Response(next(answers), json=[])

    assert keycloak_client(handler).events(0, 0, 10) == []


def test_client_renews_token_before_it_expires() -> None:
    now = [0.0]
    issued: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            issued.append("x")
            return httpx.Response(
                200, json={"access_token": f"t{len(issued)}", "expires_in": 60}
            )
        return httpx.Response(200, json=[])

    client = keycloak_client(handler, clock=lambda: now[0])
    client.events(0, 0, 10)
    now[0] = 29
    client.events(0, 0, 10)
    now[0] = 31
    client.events(0, 0, 10)

    assert len(issued) == 2


@pytest.mark.parametrize(
    ("token_status", "events_status", "message"),
    [
        (401, 200, "Keycloak refused the API's service account (HTTP 401)."),
        (200, 403, "Keycloak did not return the events (HTTP 403)."),
        (200, 401, "Keycloak did not accept the API's token."),
    ],
)
def test_client_problems_become_keycloak_unavailable(
    token_status: int, events_status: int, message: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(
                token_status, json={"access_token": "t", "expires_in": 300}
            )
        return httpx.Response(events_status, json=[])

    with pytest.raises(
        KeycloakUnavailable, match=message.replace("(", r"\(").replace(")", r"\)")
    ):
        keycloak_client(handler).events(0, 0, 10)


def test_client_keycloak_not_reachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(KeycloakUnavailable, match="not reachable"):
        keycloak_client(handler).events(0, 0, 10)


def test_client_user_email_of_deleted_user_is_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        return httpx.Response(404, json={"error": "User not found"})

    assert keycloak_client(handler).user_email("gone") is None


def test_secret_is_required_outside_local_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_keycloak_client.cache_clear()
    try:
        monkeypatch.setenv(
            "OIDC_ISSUER", "https://login.example.com/realms/bizpartnercheck"
        )
        monkeypatch.delenv("KEYCLOAK_API_CLIENT_SECRET", raising=False)
        assert get_keycloak_client() is None

        get_keycloak_client.cache_clear()
        monkeypatch.setenv("KEYCLOAK_API_CLIENT_SECRET", "s3cret")
        client = get_keycloak_client()
        assert client is not None
        assert (
            client.admin_url == "https://login.example.com/admin/realms/bizpartnercheck"
        )
    finally:
        get_keycloak_client.cache_clear()


# ------------------------------------------------------------------ append-only table


def add_event(
    db: Session,
    *,
    event_type: EventType = EventType.SIGN_IN,
    occurred_at: datetime | None = None,
    organization_id: uuid.UUID | None = TEST_ORGANIZATION_ID,
    summary: str = "Signed in with password",
    actor_email: str | None = "anna@example.com",
) -> SecurityEvent:
    event = SecurityEvent(
        organization_id=organization_id,
        occurred_at=occurred_at or datetime(2026, 11, 5, 10, 0, tzinfo=UTC),
        event_type=event_type.value,
        actor_email=actor_email,
        source=SOURCE_KEYCLOAK,
        details={"summary": summary},
    )
    db.add(event)
    db.flush()
    return event


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE security_events SET event_type = 'SIGN_OUT'",
        "DELETE FROM security_events",
    ],
)
def test_log_entries_cannot_be_changed_or_deleted(db: Session, statement: str) -> None:
    add_event(db)

    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.execute(text(statement))


def test_deleting_needs_explicit_permission(db: Session) -> None:
    add_event(db)

    with db.begin_nested():
        db.execute(text("SET LOCAL bizpartnercheck.allow_security_event_delete = 'on'"))
        db.execute(text("DELETE FROM security_events"))
        db.execute(
            text("SET LOCAL bizpartnercheck.allow_security_event_delete = 'off'")
        )

    assert stored(db) == []


def test_record_event_for_app_actions(db: Session) -> None:
    admin = CurrentUser(id="admin-1", email="admin@example.com", name="Anna Admin")

    for event_type in (EventType.API_TOKEN_CREATED, EventType.API_TOKEN_REVOKED):
        record_event(
            db,
            organization_id=TEST_ORGANIZATION_ID,
            event_type=event_type,
            actor=admin,
            summary="API token ERP created",
            details={"token_name": "ERP"},
        )
    db.flush()

    rows = stored(db)
    assert [row.event_type for row in rows] == [
        "API_TOKEN_CREATED",
        "API_TOKEN_REVOKED",
    ]
    assert rows[0].source == SOURCE_APP
    assert rows[0].actor_email == "admin@example.com"
    assert rows[0].details == {"summary": "API token ERP created", "token_name": "ERP"}
    assert rows[0].external_id is None


# ------------------------------------------------------------------ API


@pytest.fixture
def admin(anonymous_client: TestClient, admin_token: str) -> TestClient:
    anonymous_client.headers["Authorization"] = f"Bearer {admin_token}"
    return anonymous_client


def test_log_needs_sign_in(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/api/v1/security-events").status_code == 401


@pytest.mark.parametrize(
    "path", ["/api/v1/security-events", "/api/v1/security-events/export"]
)
def test_log_is_only_for_org_admins(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"


def test_admin_sees_own_organisation_only(admin: TestClient, db: Session) -> None:
    other = Organization(name="Other customer")
    db.add(other)
    db.flush()
    add_event(db, summary="mine")
    add_event(db, summary="theirs", organization_id=other.id)
    add_event(db, summary="nobody's", organization_id=None)

    response = admin.get("/api/v1/security-events")

    assert response.status_code == 200
    assert [item["summary"] for item in response.json()["items"]] == ["mine"]


def test_log_lists_newest_first_with_all_fields(admin: TestClient, db: Session) -> None:
    add_event(db, summary="older", occurred_at=datetime(2026, 11, 1, tzinfo=UTC))
    newer = add_event(db, summary="newer", event_type=EventType.SIGN_IN_FAILED)

    body = admin.get("/api/v1/security-events").json()

    assert [item["summary"] for item in body["items"]] == ["newer", "older"]
    assert body["items"][0] == {
        "id": str(newer.id),
        "occurred_at": "2026-11-05T10:00:00Z",
        "event_type": "SIGN_IN_FAILED",
        "summary": "newer",
        "actor_email": "anna@example.com",
        "subject_email": None,
        "ip_address": None,
        "source": "keycloak",
    }
    assert body["next_cursor"] is None


def test_filter_by_event_type(admin: TestClient, db: Session) -> None:
    add_event(db, event_type=EventType.SIGN_IN, summary="in")
    add_event(db, event_type=EventType.ROLE_ASSIGNED, summary="role")

    body = admin.get(
        "/api/v1/security-events", params={"event_type": "ROLE_ASSIGNED"}
    ).json()

    assert [item["summary"] for item in body["items"]] == ["role"]


def test_unknown_event_type_is_rejected(admin: TestClient) -> None:
    response = admin.get("/api/v1/security-events", params={"event_type": "HACKED"})

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "event_type"


def test_filter_by_time(admin: TestClient, db: Session) -> None:
    for day in (1, 2, 3):
        add_event(
            db,
            summary=f"day {day}",
            occurred_at=datetime(2026, 11, day, 12, tzinfo=UTC),
        )

    body = admin.get(
        "/api/v1/security-events",
        params={"from": "2026-11-02T00:00:00+00:00", "to": "2026-11-03T00:00:00Z"},
    ).json()

    assert [item["summary"] for item in body["items"]] == ["day 2"]


def test_time_without_zone_is_utc(admin: TestClient, db: Session) -> None:
    add_event(db, summary="noon", occurred_at=datetime(2026, 11, 2, 12, tzinfo=UTC))

    body = admin.get(
        "/api/v1/security-events", params={"from": "2026-11-02T12:00:00"}
    ).json()

    assert [item["summary"] for item in body["items"]] == ["noon"]


def test_from_must_be_before_to(admin: TestClient) -> None:
    response = admin.get(
        "/api/v1/security-events",
        params={"from": "2026-11-03T00:00:00Z", "to": "2026-11-02T00:00:00Z"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "from"


def test_paging_with_cursor(admin: TestClient, db: Session) -> None:
    same_time = datetime(2026, 11, 5, tzinfo=UTC)
    for i in range(5):
        add_event(
            db, summary=f"e{i}", occurred_at=same_time + timedelta(minutes=i // 2)
        )

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["before"] = cursor
        body = admin.get("/api/v1/security-events", params=params).json()
        seen += [item["summary"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if not cursor:
            break

    assert pages == 3
    assert sorted(seen) == ["e0", "e1", "e2", "e3", "e4"]  # every entry exactly once


def test_broken_cursor_is_rejected(admin: TestClient) -> None:
    response = admin.get("/api/v1/security-events", params={"before": "not-a-cursor"})

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "before"


def test_limit_is_bounded(admin: TestClient) -> None:
    assert (
        admin.get("/api/v1/security-events", params={"limit": 201}).status_code == 422
    )
    assert admin.get("/api/v1/security-events", params={"limit": 0}).status_code == 422


def test_opening_the_log_copies_keycloak_events(
    admin: TestClient, keycloak: FakeKeycloak
) -> None:
    keycloak.user_events = [user_event("LOGIN", credential_type="otp")]
    app.dependency_overrides[get_keycloak_client] = lambda: keycloak

    body = admin.get("/api/v1/security-events").json()

    assert body["sync"] == {"ok": True, "message": None, "imported": 1}
    assert [item["summary"] for item in body["items"]] == [
        "Signed in with password and one-time code"
    ]


def test_log_still_shows_when_keycloak_is_down(
    admin: TestClient, db: Session, keycloak: FakeKeycloak
) -> None:
    add_event(db, summary="earlier")
    keycloak.down = True
    app.dependency_overrides[get_keycloak_client] = lambda: keycloak

    body = admin.get("/api/v1/security-events").json()

    assert body["sync"]["ok"] is False
    assert "Keycloak is not reachable" in body["sync"]["message"]
    assert [item["summary"] for item in body["items"]] == ["earlier"]


def test_log_says_when_keycloak_is_not_configured(admin: TestClient) -> None:
    body = admin.get("/api/v1/security-events").json()

    assert body["sync"]["ok"] is False
    assert "not configured" in body["sync"]["message"]


def test_later_pages_do_not_sync(
    admin: TestClient, db: Session, keycloak: FakeKeycloak
) -> None:
    for i in range(3):
        add_event(db, summary=f"e{i}", occurred_at=datetime(2026, 11, 1, i, tzinfo=UTC))
    app.dependency_overrides[get_keycloak_client] = lambda: keycloak
    cursor = admin.get("/api/v1/security-events", params={"limit": 1}).json()[
        "next_cursor"
    ]
    keycloak.calls.clear()

    admin.get("/api/v1/security-events", params={"limit": 1, "before": cursor})

    assert keycloak.calls == []


def read_csv(response: Any) -> list[list[str]]:
    content = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(content)))


def test_export_csv(admin: TestClient, db: Session) -> None:
    add_event(db, summary="Signed in with password")

    response = admin.get("/api/v1/security-events/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="security-log-'
    )
    rows = read_csv(response)
    assert rows[0] == [
        "time_utc",
        "event",
        "summary",
        "actor",
        "concerns",
        "ip_address",
        "source",
    ]
    assert rows[1] == [
        "2026-11-05T10:00:00+00:00",
        "SIGN_IN",
        "Signed in with password",
        "anna@example.com",
        "",
        "",
        "keycloak",
    ]


def test_export_neutralises_spreadsheet_formulas(
    admin: TestClient, db: Session
) -> None:
    add_event(
        db, summary='=HYPERLINK("http://evil.example")', actor_email="+1@example.com"
    )

    rows = read_csv(admin.get("/api/v1/security-events/export"))

    assert rows[1][2] == '\'=HYPERLINK("http://evil.example")'
    assert rows[1][3] == "'+1@example.com"


def test_export_uses_filters_and_is_logged(admin: TestClient, db: Session) -> None:
    add_event(db, event_type=EventType.SIGN_IN)
    add_event(db, event_type=EventType.ROLE_ASSIGNED, summary="role")

    rows = read_csv(
        admin.get(
            "/api/v1/security-events/export", params={"event_type": "ROLE_ASSIGNED"}
        )
    )

    assert [row[2] for row in rows[1:]] == ["role"]
    exported = db.scalars(
        select(SecurityEvent).where(SecurityEvent.event_type == EventType.DATA_EXPORTED)
    ).one()
    assert exported.actor_id == "admin-1"
    assert exported.actor_email == "admin@example.com"
    assert exported.organization_id == TEST_ORGANIZATION_ID
    assert exported.source == SOURCE_APP
    assert exported.details["rows"] == 1
    assert exported.details["event_type"] == "ROLE_ASSIGNED"
    assert exported.details["summary"] == "Security log exported (1 entry)"

    # The export shows up in the log itself.
    items = admin.get(
        "/api/v1/security-events", params={"event_type": "DATA_EXPORTED"}
    ).json()["items"]
    assert items[0]["actor_email"] == "admin@example.com"
