"""Import the BMF list regularly while the API runs (T4.3.2).

S4.3 requires an import at least every 24 hours. We import every 6 hours by default,
so one or two failed runs (BMF site down) still keep the list younger than 24 hours.
BMF_IMPORT_INTERVAL_SECONDS sets the interval (0 switches it off, e.g. in tests).

After a restart the next import runs when the last successful one is older than the
interval, so restarting the API (or --reload) does not download the list every time.
"""

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

from starlette.concurrency import run_in_threadpool

from app.bmf.importer import ImportAlreadyRunning, download_and_import, import_status
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60
FIRST_CHECK_AFTER_SECONDS = 10
# After a failed run, try again sooner than the normal interval.
RETRY_AFTER_FAILURE_SECONDS = 15 * 60


def import_interval() -> int:
    raw = os.environ.get("BMF_IMPORT_INTERVAL_SECONDS", "")
    try:
        return max(0, int(raw)) if raw.strip() else DEFAULT_INTERVAL_SECONDS
    except ValueError:
        logger.warning("Ignoring BMF_IMPORT_INTERVAL_SECONDS=%r (not a number)", raw)
        return DEFAULT_INTERVAL_SECONDS


def seconds_until_due(
    last_success: datetime | None, interval: int, now: datetime
) -> float:
    if last_success is None:
        return 0.0
    return max(0.0, (last_success + timedelta(seconds=interval) - now).total_seconds())


def import_if_due(
    interval: int, now: Callable[[], datetime] = lambda: datetime.now(UTC)
) -> float:
    """Import when due; returns how many seconds to wait before the next look."""
    with SessionLocal() as db:
        status = import_status(db)
        last = status.last_success.finished_at if status.last_success else None
        wait = seconds_until_due(last, interval, now())
        if wait > 0:
            return wait
        try:
            record = download_and_import(db, trigger="schedule")
        except ImportAlreadyRunning:
            return RETRY_AFTER_FAILURE_SECONDS
    if record.status == "SUCCESS":
        return float(interval)
    return float(min(interval, RETRY_AFTER_FAILURE_SECONDS))


async def _run_forever(interval: int) -> None:
    await asyncio.sleep(FIRST_CHECK_AFTER_SECONDS)
    while True:
        try:
            wait = await run_in_threadpool(import_if_due, interval)
        except Exception:  # e.g. database down: try again later
            logger.exception("BMF list: scheduled import failed")
            wait = RETRY_AFTER_FAILURE_SECONDS
        await asyncio.sleep(wait)


@contextlib.asynccontextmanager
async def bmf_import_schedule() -> AsyncIterator[None]:
    """Runs the import in the background while the API is up (used in app/main.py)."""
    interval = import_interval()
    task = asyncio.create_task(_run_forever(interval)) if interval > 0 else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
