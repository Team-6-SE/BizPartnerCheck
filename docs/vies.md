# VIES check (VAT number)

## Context

A partner's VAT number must be confirmed by **VIES**, the EU Commission service that asks the tax office
of the country. We need to know which API we call, how we read its answer, and what happens when VIES
is slow or down.

## Decision

**API:** the public VIES REST API, no key needed.

```
GET https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{country}/vat/{number}
e.g.  .../ms/AT/vat/U33864707
```

Country code and number come from the stored VAT number (`ATU33864707` → `AT` + `U33864707`).
Greece is `EL` and Northern Ireland `XI`, as in VIES. Example answer (shortened):

```json
{"isValid": true, "userError": "VALID", "name": "Red Bull GmbH", "address": "Am Brunnen 1\nAT-5330 Fuschl/See", ...}
```

**How we read the answer** (`backend/app/adapters/vies.py`):

| VIES answer | Our result |
|---|---|
| `isValid: true`, `userError: "VALID"` | `VALID` |
| `isValid: false`, `userError: "INVALID"` | `INVALID` |
| any other `userError` (`MS_UNAVAILABLE`, `TIMEOUT`, `SERVICE_UNAVAILABLE`, `MS_MAX_CONCURRENT_REQ`, …) | `ERROR` |
| no answer in time, not reachable, HTTP error, not JSON, unknown format | `ERROR` |

Important: VIES also sends `isValid: false` when the country's tax office was not available. So
`isValid: false` alone does **not** mean invalid. Anything we cannot read clearly is `ERROR`, never `VALID`.

**Time limits** (from `docs/architecture.md`): 8 s per call, max. 2 retries, 30 s in total. We only ask again
for temporary problems (timeout, not reachable, HTTP 5xx/429, `MS_UNAVAILABLE`, `TIMEOUT`,
`SERVICE_UNAVAILABLE`, `*_MAX_CONCURRENT_REQ*`), with a short pause (0.5 s, 1 s).

**What is stored:** every check adds one row to `check_results` (partner, source `VIES`, status, time,
the raw VIES answer as JSONB). Rows are never changed, so the history stays. The partner list shows the
latest result. `ERROR` results are stored too: they show that the number could not be confirmed at that time.

**API:**

- `POST /api/v1/partners/{id}/checks/vies` – asks VIES now, stores and returns the result (`201`).
  `ERROR` is a normal result, not an HTTP error. Unknown partner or partner of another organization → `404`.
- `GET /api/v1/partners` – each partner has `latest_vies_check` (or `null`).

**Configuration:** `VIES_BASE_URL` (optional) points to another server, e.g. a stub for staging or load tests.
Default is the EU Commission service.

## Why / Alternatives

- **SOAP API** (`checkVatService`): older, XML, same data. JSON over REST is simpler to call and to test.
- **`POST /check-vat-number`**: same answer, needs a JSON body; the `GET` form is enough for us.
- **Run the check in a background job (Celery) and answer `202`**: planned in the architecture for the full
  check run with all 5 sources. For one VIES check the request waits (max. ~30 s) to keep this step small;
  the adapter stays the same when the worker comes.
- **HTTP client:** `httpx2`, the maintained successor of `httpx` (same API). Starlette's test client already
  uses it, so we have one HTTP library instead of two.

## Tests

`tests/test_vies_adapter.py` uses fake HTTP answers (`httpx.MockTransport`): valid, invalid, timeout → ERROR,
country not available → ERROR, retries and the 30 s limit. `tests/test_vies_checks.py` replaces VIES with a fake
in the API. No test needs the internet.
