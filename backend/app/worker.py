"""Celery: the worker process that executes check runs (S5.1, T5.1.2).

The API puts a run into the Redis queue and answers at once; one or more workers take
runs from the queue and ask the sources. Start a worker locally with

    uv run celery -A app.worker worker --loglevel=info --pool=threads --concurrency=4

(--pool=threads because the default pool does not work on Windows). Without
CELERY_BROKER_URL the API runs checks in its own process instead (see app/checks/queue.py).
"""

import os

# Loads the .env file (DATABASE_URL, CELERY_BROKER_URL) before anything reads it.
import app.db.session  # noqa: F401
from celery import Celery

DEFAULT_BROKER_URL = "redis://localhost:6379/0"

celery_app = Celery(
    "bizpartnercheck",
    broker=os.environ.get("CELERY_BROKER_URL") or DEFAULT_BROKER_URL,
    include=["app.checks.tasks"],
)
celery_app.conf.update(
    # A run is acknowledged only after it finished: if a worker dies, another one gets
    # it again (execute_run skips runs that are no longer "running").
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Results are in the database; Celery does not need to keep them.
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    # Do not let the API hang when Redis is down.
    broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 3},
)
