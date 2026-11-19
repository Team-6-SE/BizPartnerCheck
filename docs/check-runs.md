# Check runs (S5.1)

One click on "Check" starts a **check run**: all sources are asked for one partner at the
same time. The start returns at once; the client polls until the run is finished.

## API

### Start a run

`POST /api/v1/partners/{partner_id}/runs` → `202 Accepted`

```json
{
  "id": "6f1c…",
  "partner_id": "e475…",
  "status": "running",
  "sources": ["VIES", "BMF", "HFU"],
  "started_at": "2026-11-19T17:10:00Z",
  "finished_at": null,
  "results": []
}
```

Errors (uniform format): `404 partner_not_found` (unknown or other organisation's partner),
`409 partner_archived`.

### Status and results

`GET /api/v1/runs/{run_id}` → `200` with the same shape. Poll every 1–2 s until `status` is
`complete` or `incomplete`. `results` has one entry per source that has answered, in the
order of `sources`; a source without a result is still waiting. Each result is the same
`CheckRead` as on the partner endpoints (`source`, `status`, `checked_at`, `message`,
`company_name`, `address`, `consultation_number`, `data_as_of`).

`404 run_not_found` for unknown runs and runs of other organisations.

## Status of a run

| Status | Meaning |
|---|---|
| `running` | Sources are being asked |
| `complete` | Every source gave a result that is not `ERROR` (`OK`, `FINDING`, `REVIEW`, `NOT_APPLICABLE`) |
| `incomplete` | At least one source failed or did not answer in time (`ERROR`) |

- Sources that need a VAT number (VIES, HFU) give `NOT_APPLICABLE` for partners without one.
- A source that is still asking when the time limit is over (`CHECK_RUN_DEADLINE_SECONDS`,
  default 30) gets `ERROR` ("did not answer within 30 s"); the others are stored normally.
- `ERROR` results are stored too, as evidence that the source could not be asked.

## Data model

- `check_runs`: `id`, `organization_id`, `partner_id`, `status`, `sources` (JSON list),
  `started_by` (Keycloak user ID), `started_at`, `finished_at`.
- `check_results.run_id` links each result to its run (empty for older single-source checks).
- The run's final status and all its results are stored in one transaction
  (`app/checks/runs.py`, `finish_run`).

## Code

| File | What |
|---|---|
| `backend/app/checks/runs.py` | `start_run`, `finish_run`, `final_status` |
| `backend/app/checks/executor.py` | `execute_run`: asks all sources in parallel with the time limit; `default_adapters` for the worker |
| `backend/app/checks/router.py` | The two endpoints |

**Adding a source** (e.g. Firmenbuch, GISA): add its adapter to `get_run_adapters` and its
name to `RUN_SOURCES` in `app/checks/router.py`.

## Queue and worker (T5.1.2)

| `CELERY_BROKER_URL` | Who executes a run |
|---|---|
| set (e.g. `redis://localhost:6379/0`) | The API puts the run ID into the Redis queue; a **Celery worker** asks the sources. More workers share the runs. |
| not set | The API itself, right after the response (FastAPI background task). No Redis needed: fine for development and tests. |

Both call the same `execute_run`, so results are the same.

- Start a worker locally: `uv run celery -A app.worker worker --loglevel=info --pool=threads --concurrency=4`
  (`--pool=threads` because Celery's default pool does not run on Windows).
- If Redis cannot be reached when a run starts, the API answers `503 check_queue_unavailable` and
  closes the run as `incomplete`.
- A run is acknowledged in the queue only when it is finished: if a worker dies, another one takes
  it again. Runs that are no longer `running` are skipped.
- Staging (`infra/compose.deploy.yml`): `redis` and `worker` services; more workers with
  `docker compose up -d --scale worker=2`.

| File | What |
|---|---|
| `backend/app/worker.py` | Celery app and its settings |
| `backend/app/checks/tasks.py` | Task `checks.run_check` |
| `backend/app/checks/queue.py` | Queue or API process, depending on `CELERY_BROKER_URL` |

## Crash safety (T5.1.5)

If the API process or a worker stops in the middle of a run, the run would stay `running`
forever. A run that is still `running` more than `CHECK_RUN_STALE_SECONDS` (default 120) after it
started is therefore closed as **incomplete**, with an `ERROR` result for every source
("The check was interrupted before … answered"). This happens

- when the API starts and when a Celery worker starts (`CHECK_RUN_STARTUP_CLEANUP=0` switches it
  off; the tests do that),
- whenever `GET /runs/{id}` reads such a run, so nobody has to wait for a restart.

A worker that answers after its run was closed does not overwrite it (`finish_run` re-reads the
run with a row lock). The 120 s leave room for runs that wait in the queue while all workers are
busy; every run itself finishes within `CHECK_RUN_DEADLINE_SECONDS` (30).

## Not done yet

- **Performance test (T5.1.6).**
