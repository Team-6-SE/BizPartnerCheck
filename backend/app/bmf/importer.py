"""Copy the BMF list of fake companies into our database (T4.3.1).

    content = download_feed()                       # HTTP, no database connection held
    run_import(db, content, trigger="schedule")     # one transaction

The import is idempotent: importing the same feed twice changes nothing except the
"last seen" times. Entries are never deleted. An entry that is no longer in the feed
gets removed_at and is not matched any more; if it comes back, removed_at is cleared.

Every run is written to bmf_imports (history). A failed run never changes the list:
if the feed cannot be read, is empty or suddenly much shorter than our copy, the old
copy stays and its age shows in every BMF result.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx2 as httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.bmf.feed import FEED_URL, FeedError, parse_feed
from app.db.models import BmfImport, BmfListEntry

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 30.0
# A new feed with less than this share of our current entries is not applied.
MIN_SHARE_OF_CURRENT_LIST = 0.5
# Any fixed number; makes sure only one import runs at a time (several API workers).
_ADVISORY_LOCK_ID = 35_043_001

SUCCESS = "SUCCESS"
FAILED = "FAILED"


class ImportAlreadyRunning(RuntimeError):
    pass


def feed_url() -> str:
    """BMF_FEED_URL can point to a saved copy or a stub (staging, demos)."""
    return os.environ.get("BMF_FEED_URL") or FEED_URL


def download_feed(
    url: str | None = None, *, transport: httpx.BaseTransport | None = None
) -> bytes:
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        response = client.get(
            url or feed_url(),
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            headers={"Accept": "application/rss+xml, application/xml"},
        )
    response.raise_for_status()
    return response.content


@dataclass(frozen=True)
class ImportResult:
    status: str
    entries_in_feed: int = 0
    entries_added: int = 0
    entries_removed: int = 0
    error: str | None = None


def run_import(
    db: Session,
    content: bytes,
    *,
    trigger: str,
    started_by: str | None = None,
    started_at: datetime | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> BmfImport:
    """Apply a downloaded feed to the stored list and record the run. Commits."""
    started = started_at or now()
    if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:id)"), {"id": _ADVISORY_LOCK_ID}):
        db.rollback()
        raise ImportAlreadyRunning("Another BMF import is running right now.")

    try:
        result = _apply(db, content, now())
    except FeedError as exc:
        db.rollback()  # keep the old list exactly as it was
        result = ImportResult(FAILED, error=str(exc))

    record = BmfImport(
        started_at=started,
        finished_at=now(),
        status=result.status,
        trigger=trigger,
        started_by=started_by,
        entries_in_feed=result.entries_in_feed,
        entries_added=result.entries_added,
        entries_removed=result.entries_removed,
        error=result.error,
    )
    db.add(record)
    db.commit()
    if result.status == SUCCESS:
        logger.info(
            "BMF list imported: %d entries, %d new, %d removed",
            result.entries_in_feed,
            result.entries_added,
            result.entries_removed,
        )
    else:
        logger.warning("BMF list import failed: %s", result.error)
    return record


def record_failure(
    db: Session,
    error: str,
    *,
    trigger: str,
    started_by: str | None = None,
    started_at: datetime,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> BmfImport:
    """The feed could not be downloaded: record it, keep the list."""
    record = BmfImport(
        started_at=started_at,
        finished_at=now(),
        status=FAILED,
        trigger=trigger,
        started_by=started_by,
        error=error,
    )
    db.add(record)
    db.commit()
    logger.warning("BMF list import failed: %s", error)
    return record


def _apply(db: Session, content: bytes, seen_at: datetime) -> ImportResult:
    feed = parse_feed(content)
    if not feed.entries:
        raise FeedError("The BMF feed contains no entries; the stored list was kept.")
    if feed.skipped:
        logger.warning("BMF feed: %d entries without name or date were skipped", feed.skipped)

    stored = {entry.entry_key: entry for entry in db.scalars(select(BmfListEntry))}
    active = sum(1 for entry in stored.values() if entry.removed_at is None)
    if len(feed.entries) < active * MIN_SHARE_OF_CURRENT_LIST:
        raise FeedError(
            f"The BMF feed has only {len(feed.entries)} entries, our list has {active}; "
            "the feed looks incomplete, so the stored list was kept."
        )

    added = 0
    in_feed: set[str] = set()
    for item in feed.entries:
        key = item.key
        if key in in_feed:
            continue  # the very same entry twice in one feed
        in_feed.add(key)
        entry = stored.get(key)
        if entry is None:
            db.add(
                BmfListEntry(
                    entry_key=key,
                    name=item.name,
                    normalized_name=item.normalized_name,
                    address=item.address,
                    vat_number=item.vat_number,
                    ur_number=item.ur_number,
                    register_number=item.register_number,
                    birth_date=item.birth_date,
                    published_on=item.published_on,
                    fake_since=item.fake_since,
                    decision_final_on=item.decision_final_on,
                    link=item.link,
                    first_seen_at=seen_at,
                    last_seen_at=seen_at,
                )
            )
            added += 1
        else:
            entry.last_seen_at = seen_at
            entry.removed_at = None  # back on the list

    removed = 0
    for key, entry in stored.items():
        if key not in in_feed and entry.removed_at is None:
            entry.removed_at = seen_at
            removed += 1

    db.flush()
    return ImportResult(SUCCESS, len(in_feed), added, removed)


@dataclass(frozen=True)
class ImportStatus:
    last_success: BmfImport | None
    last_attempt: BmfImport | None
    active_entries: int


def import_status(db: Session) -> ImportStatus:
    last_success = db.scalar(
        select(BmfImport)
        .where(BmfImport.status == SUCCESS)
        .order_by(BmfImport.finished_at.desc())
        .limit(1)
    )
    last_attempt = db.scalar(
        select(BmfImport).order_by(BmfImport.finished_at.desc()).limit(1)
    )
    active = db.scalar(
        select(func.count()).select_from(BmfListEntry).where(BmfListEntry.removed_at.is_(None))
    )
    return ImportStatus(last_success, last_attempt, active or 0)


def download_and_import(
    db: Session,
    *,
    trigger: str,
    started_by: str | None = None,
    download: Callable[[], bytes] = download_feed,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> BmfImport:
    """Download the feed and import it; a download problem is recorded as FAILED."""
    started = now()
    # No database transaction is open while downloading.
    db.commit()
    try:
        content = download()
    except httpx.HTTPError as exc:
        message = f"The BMF feed could not be downloaded ({type(exc).__name__})."
        return record_failure(
            db, message, trigger=trigger, started_by=started_by, started_at=started, now=now
        )
    return run_import(
        db, content, trigger=trigger, started_by=started_by, started_at=started, now=now
    )
