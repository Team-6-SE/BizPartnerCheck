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
| `backend/app/checks/executor.py` | `execute_run`: asks all sources in parallel with the time limit |
| `backend/app/checks/router.py` | The two endpoints |

**Adding a source** (e.g. Firmenbuch, GISA): add its adapter to `get_run_adapters` and its
name to `RUN_SOURCES` in `app/checks/router.py`.

## Not done yet

- **Queue and worker (T5.1.2):** for now the run is executed as a FastAPI background task in
  the API process. The Celery worker will call the same `execute_run`.
- **Crash safety (T5.1.5):** runs left `running` after a crash are not yet marked incomplete.
- **Progress UI (T5.1.4):** the web app still uses the single-source endpoints.
