"""Importing the BMF list: idempotent, history, failures keep the list (T4.3.1, T4.3.2)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2 as httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bmf.background import import_interval, seconds_until_due
from app.bmf.importer import (
    download_and_import,
    download_feed,
    import_status,
    run_import,
)
from app.db.models import BmfImport, BmfListEntry

SAMPLE = Path(__file__).parent / "fixtures" / "bmf_feed_sample.xml"
T0 = datetime(2026, 11, 9, 6, 0, tzinfo=UTC)


def sample() -> bytes:
    return SAMPLE.read_bytes()


def without(content: bytes, name: str) -> bytes:
    """The sample feed without the item of this company."""
    text = content.decode("iso-8859-1")
    lines = [line for line in text.splitlines() if f"[CDATA[{name}]]" not in line]
    return "\n".join(lines).encode("iso-8859-1")


def active(db: Session) -> list[BmfListEntry]:
    return list(
        db.scalars(select(BmfListEntry).where(BmfListEntry.removed_at.is_(None)))
    )


def test_first_import_stores_all_entries(db: Session) -> None:
    record = run_import(db, sample(), trigger="schedule", now=lambda: T0)

    assert record.status == "SUCCESS"
    assert record.entries_in_feed == 6
    assert record.entries_added == 6
    assert record.entries_removed == 0
    assert len(active(db)) == 6
    entry = db.scalar(
        select(BmfListEntry).where(BmfListEntry.vat_number == "ATU11111111")
    )
    assert entry is not None
    assert entry.normalized_name == "muster scheinbau"
    assert entry.first_seen_at == entry.last_seen_at == T0


def test_import_is_idempotent(db: Session) -> None:
    run_import(db, sample(), trigger="schedule", now=lambda: T0)
    later = T0 + timedelta(hours=6)

    record = run_import(db, sample(), trigger="schedule", now=lambda: later)

    assert record.entries_added == 0
    assert record.entries_removed == 0
    entries = active(db)
    assert len(entries) == 6
    assert all(e.first_seen_at == T0 and e.last_seen_at == later for e in entries)


def test_entry_no_longer_in_feed_is_marked_not_deleted(db: Session) -> None:
    run_import(db, sample(), trigger="schedule", now=lambda: T0)
    later = T0 + timedelta(hours=6)

    record = run_import(
        db,
        without(sample(), "Alpen Trockenbau KG"),
        trigger="schedule",
        now=lambda: later,
    )

    assert record.entries_removed == 1
    gone = db.scalar(
        select(BmfListEntry).where(BmfListEntry.name == "Alpen Trockenbau KG")
    )
    assert gone is not None and gone.removed_at == later
    assert len(active(db)) == 5


def test_entry_back_on_the_list_is_active_again(db: Session) -> None:
    run_import(db, sample(), trigger="schedule", now=lambda: T0)
    run_import(
        db, without(sample(), "Alpen Trockenbau KG"), trigger="schedule", now=lambda: T0
    )

    record = run_import(db, sample(), trigger="schedule", now=lambda: T0)

    assert record.entries_added == 0  # the same row, not a new one
    assert len(active(db)) == 6


@pytest.mark.parametrize(
    "content",
    [b"<html>maintenance</html>", b'<rss version="2.0"><channel></channel></rss>'],
)
def test_failed_import_keeps_the_list_and_is_recorded(
    db: Session, content: bytes
) -> None:
    run_import(db, sample(), trigger="schedule", now=lambda: T0)

    record = run_import(db, content, trigger="manual", started_by="ops@example.com")

    assert record.status == "FAILED"
    assert record.error
    assert record.started_by == "ops@example.com"
    assert len(active(db)) == 6


def test_much_shorter_feed_is_not_applied(db: Session) -> None:
    run_import(db, sample(), trigger="schedule", now=lambda: T0)
    short = sample()
    for name in ("Muster Scheinbau GmbH", "NOVÁK Péter", "Glanz Reinigung OG"):
        short = without(short, name)

    record = run_import(db, short, trigger="schedule")

    assert record.status == "FAILED"
    assert "incomplete" in (record.error or "")
    assert len(active(db)) == 6


def test_history_and_status(db: Session) -> None:
    run_import(db, sample(), trigger="schedule", now=lambda: T0)
    run_import(db, b"broken", trigger="schedule", now=lambda: T0 + timedelta(hours=6))

    current = import_status(db)

    assert db.query(BmfImport).count() == 2
    assert current.last_success is not None
    assert current.last_success.finished_at == T0
    assert current.last_attempt is not None
    assert current.last_attempt.status == "FAILED"
    assert current.active_entries == 6


def test_download_problem_is_recorded_as_failed(db: Session) -> None:
    def down() -> bytes:
        raise httpx.ConnectError("no route")

    record = download_and_import(db, trigger="schedule", download=down)

    assert record.status == "FAILED"
    assert "could not be downloaded" in (record.error or "")
    assert import_status(db).last_success is None


def test_download_uses_the_feed_url() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=sample())

    content = download_feed(
        "https://bmf.test/rss_lsu.asp", transport=httpx.MockTransport(handler)
    )

    assert content == sample()
    assert seen == ["https://bmf.test/rss_lsu.asp"]


def test_http_error_while_downloading_raises() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(503, text="down"))

    with pytest.raises(httpx.HTTPStatusError):
        download_feed("https://bmf.test/rss", transport=transport)


# --- schedule -------------------------------------------------------------------


def test_default_interval_is_well_below_24_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BMF_IMPORT_INTERVAL_SECONDS", raising=False)

    assert 0 < import_interval() <= 12 * 60 * 60


@pytest.mark.parametrize(
    ("value", "expected"), [("0", 0), ("3600", 3600), ("abc", 21600)]
)
def test_interval_from_environment(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: int
) -> None:
    monkeypatch.setenv("BMF_IMPORT_INTERVAL_SECONDS", value)

    assert import_interval() == expected


def test_next_import_is_due_after_the_interval() -> None:
    interval = 6 * 60 * 60

    assert seconds_until_due(None, interval, T0) == 0  # never imported: now
    assert seconds_until_due(T0, interval, T0 + timedelta(hours=1)) == 5 * 60 * 60
    assert seconds_until_due(T0, interval, T0 + timedelta(hours=7)) == 0
