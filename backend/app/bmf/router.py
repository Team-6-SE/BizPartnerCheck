"""Platform admin: status of the BMF list and manual import (T4.3.2)."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import PlatformAdmin
from app.bmf.importer import (
    ImportAlreadyRunning,
    download_and_import,
    download_feed,
    import_status,
)
from app.db.models import BmfImport
from app.db.session import get_db
from app.errors import api_error

router = APIRouter(prefix="/admin/bmf", tags=["platform admin"])

DbSession = Annotated[Session, Depends(get_db)]


def get_feed_downloader() -> Callable[[], bytes]:
    """FastAPI dependency, replaced in tests (no internet)."""
    return download_feed


class ImportRead(BaseModel):
    started_at: datetime
    finished_at: datetime
    status: str
    trigger: str
    started_by: str | None
    entries_in_feed: int | None
    entries_added: int | None
    entries_removed: int | None
    error: str | None

    @classmethod
    def of(cls, record: BmfImport | None) -> "ImportRead | None":
        if record is None:
            return None
        return cls(
            started_at=record.started_at,
            finished_at=record.finished_at,
            status=record.status,
            trigger=record.trigger,
            started_by=record.started_by,
            entries_in_feed=record.entries_in_feed,
            entries_added=record.entries_added,
            entries_removed=record.entries_removed,
            error=record.error,
        )


class BmfStatusRead(BaseModel):
    # The time that decides how current the BMF results are.
    last_successful_import: ImportRead | None
    last_import: ImportRead | None
    entries_on_list: int


def _status(db: Session) -> BmfStatusRead:
    current = import_status(db)
    return BmfStatusRead(
        last_successful_import=ImportRead.of(current.last_success),
        last_import=ImportRead.of(current.last_attempt),
        entries_on_list=current.active_entries,
    )


@router.get("/status", response_model=BmfStatusRead)
def bmf_status(db: DbSession, _admin: PlatformAdmin) -> BmfStatusRead:
    """When the BMF list was last imported, and how many entries it has."""
    return _status(db)


@router.post(
    "/import",
    response_model=BmfStatusRead,
    responses={409: {"description": "An import is already running"}},
)
def start_bmf_import(
    db: DbSession,
    admin: PlatformAdmin,
    download: Annotated[Callable[[], bytes], Depends(get_feed_downloader)],
) -> BmfStatusRead:
    """Import the BMF list now. A failed import is recorded and keeps the old list."""
    try:
        download_and_import(
            db, trigger="manual", started_by=admin.email or admin.id, download=download
        )
    except ImportAlreadyRunning as exc:
        raise api_error(status.HTTP_409_CONFLICT, "import_running", str(exc)) from exc
    return _status(db)
