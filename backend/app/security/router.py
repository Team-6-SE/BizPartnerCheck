"""Security log API for organisation admins (story S2.6).

GET /api/v1/security-events         newest first, filter by event type and time, paged
GET /api/v1/security-events/export  the same entries as CSV (the export itself is logged)

Only users with the role "org-admin" may read it, and only their own organisation's
entries. Details: docs/security-log.md
"""

import base64
import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Select, select, tuple_
from sqlalchemy.orm import Session

from app.auth import OrgAdmin
from app.db.models import SecurityEvent
from app.db.session import get_db
from app.errors import api_error
from app.security.events import EventType, record_event
from app.security.keycloak import (
    KeycloakAdminClient,
    get_keycloak_client,
    sync_keycloak_events,
)
from app.tenancy import get_current_organization_id

router = APIRouter(prefix="/security-events", tags=["security"])

DbSession = Annotated[Session, Depends(get_db)]
OrganizationId = Annotated[uuid.UUID, Depends(get_current_organization_id)]
Keycloak = Annotated[KeycloakAdminClient | None, Depends(get_keycloak_client)]

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_EXPORT_ROWS = 10_000


class SecurityEventRead(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    event_type: str
    summary: str
    actor_email: str | None
    subject_email: str | None
    ip_address: str | None
    source: str

    @classmethod
    def from_row(cls, row: SecurityEvent) -> "SecurityEventRead":
        return cls(
            id=row.id,
            occurred_at=row.occurred_at,
            event_type=row.event_type,
            summary=str(row.details.get("summary") or row.event_type),
            actor_email=row.actor_email,
            subject_email=row.subject_email,
            ip_address=row.ip_address,
            source=row.source,
        )


class SyncStatus(BaseModel):
    # False: Keycloak could not be asked, the newest sign-ins may be missing.
    ok: bool
    message: str | None = None
    imported: int = 0


class SecurityEventPage(BaseModel):
    items: list[SecurityEventRead]
    # Pass as `before` to get the next (older) page; null on the last page.
    next_cursor: str | None
    sync: SyncStatus


class Filters:
    """Query parameters shared by the list and the export."""

    def __init__(
        self,
        event_type: Annotated[EventType | None, Query()] = None,
        from_: Annotated[
            datetime | None,
            Query(
                alias="from",
                description="Only entries at or after this time (ISO 8601).",
            ),
        ] = None,
        to: Annotated[
            datetime | None,
            Query(description="Only entries before this time (ISO 8601)."),
        ] = None,
    ) -> None:
        self.event_type = event_type
        self.from_ = _aware(from_)
        self.to = _aware(to)
        if self.from_ and self.to and self.from_ >= self.to:
            raise api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "invalid_request",
                "from: must be earlier than to.",
                field="from",
            )

    def apply(self, query: Select[Any], organization_id: uuid.UUID) -> Select[Any]:
        query = query.where(SecurityEvent.organization_id == organization_id)
        if self.event_type:
            query = query.where(SecurityEvent.event_type == self.event_type.value)
        if self.from_:
            query = query.where(SecurityEvent.occurred_at >= self.from_)
        if self.to:
            query = query.where(SecurityEvent.occurred_at < self.to)
        return query

    def as_details(self) -> dict[str, str]:
        details = {}
        if self.event_type:
            details["event_type"] = self.event_type.value
        if self.from_:
            details["from"] = self.from_.isoformat()
        if self.to:
            details["to"] = self.to.isoformat()
        return details


def _aware(value: datetime | None) -> datetime | None:
    """Times without a time zone are read as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _encode_cursor(row: SecurityEvent) -> str:
    raw = f"{row.occurred_at.isoformat()}|{row.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        occurred_at, _, row_id = (
            base64.urlsafe_b64decode(padded).decode().partition("|")
        )
        return datetime.fromisoformat(occurred_at), uuid.UUID(row_id)
    except ValueError as exc:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_request",
            "before: not a cursor from this API.",
            field="before",
        ) from exc


def _sync(db: Session, keycloak: KeycloakAdminClient | None) -> SyncStatus:
    if keycloak is None:
        return SyncStatus(
            ok=False, message="Keycloak events are not configured for this API."
        )
    result = sync_keycloak_events(db, keycloak)
    if result.error:
        return SyncStatus(
            ok=False,
            message=f"{result.error} The newest sign-ins may be missing; try again later.",
        )
    return SyncStatus(ok=True, imported=result.imported)


@router.get("", response_model=SecurityEventPage)
def list_security_events(
    _admin: OrgAdmin,
    db: DbSession,
    organization_id: OrganizationId,
    keycloak: Keycloak,
    filters: Annotated[Filters, Depends()],
    before: Annotated[
        str | None, Query(description="next_cursor of the previous page")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> SecurityEventPage:
    """The organisation's security log, newest first."""
    # Fetch Keycloak's newest events when the first page is opened; later pages only
    # read on, so the entries don't shift while the admin pages through them.
    sync = _sync(db, keycloak) if before is None else SyncStatus(ok=True)

    query = filters.apply(select(SecurityEvent), organization_id)
    if before is not None:
        occurred_at, row_id = _decode_cursor(before)
        query = query.where(
            tuple_(SecurityEvent.occurred_at, SecurityEvent.id) < (occurred_at, row_id)
        )
    rows = db.scalars(
        query.order_by(SecurityEvent.occurred_at.desc(), SecurityEvent.id.desc()).limit(
            limit + 1
        )
    ).all()
    next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return SecurityEventPage(
        items=[SecurityEventRead.from_row(row) for row in rows[:limit]],
        next_cursor=next_cursor,
        sync=sync,
    )


CSV_COLUMNS = [
    "time_utc",
    "event",
    "summary",
    "actor",
    "concerns",
    "ip_address",
    "source",
]
# A cell starting with one of these is a formula in Excel / LibreOffice.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


@router.get("/export")
def export_security_events(
    admin: OrgAdmin,
    request: Request,
    db: DbSession,
    organization_id: OrganizationId,
    keycloak: Keycloak,
    filters: Annotated[Filters, Depends()],
) -> StreamingResponse:
    """The filtered log as CSV (newest first, at most 10,000 entries)."""
    _sync(db, keycloak)
    query = filters.apply(select(SecurityEvent), organization_id)
    rows = db.scalars(
        query.order_by(SecurityEvent.occurred_at.desc(), SecurityEvent.id.desc()).limit(
            MAX_EXPORT_ROWS
        )
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        item = SecurityEventRead.from_row(row)
        writer.writerow(
            _cell(value)
            for value in (
                item.occurred_at.astimezone(UTC).isoformat(timespec="seconds"),
                item.event_type,
                item.summary,
                item.actor_email,
                item.subject_email,
                item.ip_address,
                item.source,
            )
        )

    # Exports are security events themselves (who took which data out, and when).
    record_event(
        db,
        organization_id=organization_id,
        event_type=EventType.DATA_EXPORTED,
        actor=admin,
        summary=f"Security log exported ({len(rows)} {'entry' if len(rows) == 1 else 'entries'})",
        ip_address=request.client.host if request.client else None,
        details={"export": "security_log", "rows": len(rows), **filters.as_details()},
    )
    db.commit()

    filename = f"security-log-{datetime.now(UTC):%Y-%m-%d}.csv"
    return StreamingResponse(
        iter(["﻿" + buffer.getvalue()]),  # BOM: Excel then reads umlauts correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
