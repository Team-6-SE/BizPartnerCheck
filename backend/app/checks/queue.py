"""Where a check run is executed after the API answered (S5.1, T5.1.2).

    CELERY_BROKER_URL set     the run goes into the Redis queue; a Celery worker runs it
    CELERY_BROKER_URL empty   the API runs it itself after the response (FastAPI
                              background task): fine for development and tests

Both call the same execute_run(), so the result is the same.
"""

import os
import uuid
from collections.abc import Callable, Mapping

from fastapi import BackgroundTasks

from app.adapters.base import SourceAdapter
from app.checks.executor import SessionFactory, execute_run

RunDispatcher = Callable[
    [uuid.UUID, BackgroundTasks, Mapping[str, SourceAdapter], SessionFactory], None
]


def queue_enabled() -> bool:
    return bool(os.environ.get("CELERY_BROKER_URL"))


def run_in_background(
    run_id: uuid.UUID,
    background: BackgroundTasks,
    adapters: Mapping[str, SourceAdapter],
    sessions: SessionFactory,
) -> None:
    """Run it in the API process right after the response."""
    background.add_task(execute_run, run_id, adapters, sessions)


def enqueue_run(
    run_id: uuid.UUID,
    background: BackgroundTasks,
    adapters: Mapping[str, SourceAdapter],
    sessions: SessionFactory,
) -> None:
    """Put the run into the Redis queue. Raises if Redis cannot be reached.

    The worker builds its own adapters and sessions; only the run ID is sent.
    """
    from app.checks.tasks import run_check  # imports Celery only when it is used

    run_check.apply_async(args=[str(run_id)], retry=False)


def get_run_dispatcher() -> RunDispatcher:
    """FastAPI dependency: the queue if one is configured, else the API process."""
    return enqueue_run if queue_enabled() else run_in_background
