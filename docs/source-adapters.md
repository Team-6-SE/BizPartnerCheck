# Source adapters (common framework)

## Context

BizPartnerCheck asks five external sources about a partner: VIES, the BMF fake-company list, the ÖGK HFU list,
Firmenbuch and GISA. Each one speaks a different protocol and fails in its own way. The rules that combine the
results (traffic light, S5.2) must not contain source-specific code, and tests must never need the internet.

## Decision

Every source is an **adapter** in `backend/app/adapters/`, built on one base class (`base.py`). An adapter
only implements four methods. Everything else (time limits, retries, "no answer", the result format) is shared.

| Method | What the adapter does |
|---|---|
| `query(subject, timeout)` | Asks the source **once** and returns its answer as a dict (the raw answer). May raise `httpx` errors. |
| `interpret(raw)` | Turns the raw answer into a status, and says whether asking again could help. Anything unclear is `ERROR`. |
| `describe(status, raw)` | One sentence for people: what the result means and what to do. |
| `sample_answer(scenario, subject)` | A typical answer for the fake version (`ok`, `finding`). Required, so every adapter has a fake. |

Optional: `data_as_of(raw)` for sources whose data is imported (e.g. BMF: time of the last import).

`subject` is a `CheckSubject` with what we know about the partner: `vat_number`, and later `name` and
`register_number`. Each source uses what it needs.

### Common result

`adapter.check(subject)` returns a `SourceResult`, the same for every source:

| Field | Meaning |
|---|---|
| `source` | e.g. `VIES`, `BMF` |
| `status` | `OK`, `FINDING`, `REVIEW`, `NOT_APPLICABLE` or `ERROR` (below) |
| `explanation` | the sentence from `describe` |
| `retrieved_at` | when we asked |
| `data_as_of` | how current the source's data was; `null` for live sources |
| `data_age` | `retrieved_at - data_as_of` (0 for live sources) |
| `raw` | the answer exactly as received, or what went wrong. Kept for **every** status as evidence. |

| Status | Meaning | Example |
|---|---|---|
| `OK` | The source confirms: nothing against the partner. | VIES: VAT number valid. BMF: not on the list. |
| `FINDING` | The source reports a problem. | VIES: VAT number invalid. BMF: listed as fake company. |
| `REVIEW` | Something may be wrong; a person must look. | BMF: same name, but other identifiers. |
| `NOT_APPLICABLE` | The source does not cover this partner, so it was not asked. | Firmenbuch or GISA for a foreign company. |
| `ERROR` | No clear answer (not reachable, too slow, unknown format). **Never counts as OK.** | VIES country office down. |

Every check is stored as a new row in `check_results` (`source`, `status`, `checked_at` = `retrieved_at`,
`explanation`, `data_as_of`, `raw_response`). Rows are never changed.

### Time limits and retries

Shared in `limits.py`, defaults from `docs/architecture.md`:

- **8 s** per call, **max. 2 retries** for temporary problems, **30 s** in total.
- Pauses between tries grow: 0.5 s, 1 s. No new try when less than 1 s would be left.
- No answer in time → `ERROR` with `NO_ANSWER_IN_TIME`; not reachable → `ERROR` with `NOT_REACHABLE`. Both are retried.
- The adapter decides in `interpret` which of its own answers are temporary (VIES: `MS_UNAVAILABLE`, HTTP 5xx, …).
- **An adapter bug never breaks the request.** If `query` or `interpret` raises anything else (e.g. a `KeyError`
  on an answer nobody expected), the result is `ERROR` with `ADAPTER_FAILED`, the error is logged with its
  traceback, and the check is stored. What the source answered is kept in `raw.answer`. Bugs are not retried.
  If `describe` fails, the status stays and a neutral "could not be checked" text is used.

Change them **without code changes** through environment variables. The per-source value wins:

```
SOURCE_TIMEOUT_SECONDS=8      SOURCE_MAX_RETRIES=2      SOURCE_DEADLINE_SECONDS=30     # all sources
VIES_TIMEOUT_SECONDS=5        BMF_DEADLINE_SECONDS=60                                  # one source
```

Values that cannot be read are ignored with a warning in the log, so a typo never stops the API.

### Fake adapters

`fake.py` replaces only the call to the source. The answer still goes through the real `interpret` and
`describe` and the shared time limits, so a fake timeout behaves exactly like a real one.

Choose a fake per source with `{SOURCE}_ADAPTER`, e.g. on staging or for a demo:

| Value | Result |
|---|---|
| empty or `real` | the real source (default) |
| `fake-ok` | the source confirms (`OK`) |
| `fake-finding` | the source reports a problem (`FINDING`) |
| `fake-timeout` | no answer in time (`ERROR`, after the normal retries) |
| `fake-malformed` | an answer we cannot read (`ERROR`) |

The settings are checked **once when the API starts** (`check_adapter_settings` in `app/main.py`):

- An unknown value (e.g. `fake-okk`) stops the start with an error that lists the allowed values, so a typo on
  staging does not silently call the real service or fail every check.
- An active fake is logged as a warning: `VIES: FAKE adapter active (VIES_ADAPTER=fake-finding) …`

**Fake results are marked.** Check results are evidence (S6.1), so every fake result (also timeouts and errors)
has `"fake": true` in the stored raw answer and can never be mistaken for a real answer.

New sources must be added to `SOURCES` in `app/main.py` so their setting is checked at startup.

### Adding a new source

1. Create `backend/app/adapters/<source>.py` with a class based on `SourceAdapter`, set `source = "<NAME>"`
   and implement the four methods.
2. Add a FastAPI dependency `get_<source>_adapter()` that returns `with_fake_from_env(<Adapter>())`, and add the
   source name to `SOURCES` in `app/main.py`.
3. Add a route that calls `_run_check(...)` in `app/partners/router.py`.
4. Tests: fake HTTP answers (`httpx.MockTransport`) for the adapter, and the fake adapter in API tests.

## Why / Alternatives

- **One status set instead of each source's own words** (`VALID`/`INVALID` for VIES, "listed" for BMF, …):
  the rules and the UI can then treat every source the same. Source-specific wording stays in `describe`
  and in UI labels (VIES `OK` is shown as "Valid"). Existing VIES rows were renamed by the migration
  (`VALID` → `OK`, `INVALID` → `FINDING`).
- **`REVIEW` as its own status** instead of `FINDING` or `OK`: S4.3 requires a name-only BMF match to be shown
  as "possible match – please review", never as OK, but it is not proof either.
- **`NOT_APPLICABLE` added now** (Epic E4 lists it): Firmenbuch and GISA only know Austrian companies. Adding it in
  this migration avoids another change of the status constraint later. The `status` column is 20 characters long.
- **Store the explanation** instead of only building it when reading: the sentence the user saw is part of the
  evidence (S6.1), and it stays the same even if the wording in the code changes later.
- **Fakes through an environment variable** instead of a separate fake server: works in tests, locally and on
  staging with the same code, and never needs the internet.
- **Celery worker for checks:** still planned for the full check run (`docs/architecture.md`). Adapters are plain
  synchronous classes, so they work the same in a request and in a worker.
