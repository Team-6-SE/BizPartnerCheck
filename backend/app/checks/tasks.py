"""Celery task that executes one check run (S5.1, T5.1.2)."""

import uuid

from celery.signals import worker_ready

from app.checks.executor import default_adapters, execute_run
from app.checks.runs import close_stale_runs_at_startup
from app.db.session import SessionLocal
from app.worker import celery_app

TASK_NAME = "checks.run_check"


@celery_app.task(name=TASK_NAME)
def run_check(run_id: str) -> None:
    """Ask all sources of the run and store the results (the same code as without a queue)."""
    execute_run(uuid.UUID(run_id), default_adapters(SessionLocal), SessionLocal)


@worker_ready.connect
def close_interrupted_runs(**_kwargs: object) -> None:
    """When a worker starts, close runs that a stopped worker left "running" (T5.1.5)."""
    close_stale_runs_at_startup(SessionLocal)
