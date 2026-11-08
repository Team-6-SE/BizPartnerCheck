"""Copy Keycloak events into the security log every few minutes, while the API runs.

Keycloak deletes its own events after 30 days (eventsExpiration in the realm). Copying
regularly keeps them in our log even if nobody opens the log page for a while.
SECURITY_EVENTS_SYNC_SECONDS sets the interval (default 300; 0 switches it off).
"""

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.db.session import SessionLocal
from app.security.keycloak import get_keycloak_client, sync_keycloak_events

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 300
FIRST_RUN_AFTER_SECONDS = 10


def sync_interval() -> int:
    raw = os.environ.get("SECURITY_EVENTS_SYNC_SECONDS", "")
    try:
        return max(0, int(raw)) if raw.strip() else DEFAULT_INTERVAL_SECONDS
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS


def sync_once() -> None:
    client = get_keycloak_client()
    if client is None:
        return
    with SessionLocal() as db:
        result = sync_keycloak_events(db, client)
    if result.error:
        logger.warning("Security log: Keycloak events not copied: %s", result.error)
    elif result.imported:
        logger.info("Security log: %d Keycloak events copied", result.imported)


async def _run_forever(interval: int) -> None:
    await asyncio.sleep(FIRST_RUN_AFTER_SECONDS)
    while True:
        try:
            await run_in_threadpool(sync_once)
        except Exception:  # e.g. database down: try again next time
            logger.exception("Security log: copying Keycloak events failed")
        await asyncio.sleep(interval)


@contextlib.asynccontextmanager
async def security_event_sync(_app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: runs the copying in the background while the API is up."""
    interval = sync_interval()
    task = asyncio.create_task(_run_forever(interval)) if interval > 0 else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
