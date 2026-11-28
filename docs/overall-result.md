# Overall result: the traffic light (S5.2)

Every finished check run gets one overall result, **GREEN**, **YELLOW** or **RED**, with a
short explanation, plus the explained result of every source. Users can decide quickly and
still see why.

## Rules

The worst level of all sources wins:

| Level | When | Meaning for the user |
|---|---|---|
| **RED** | A source has a `FINDING` | A problem was found (e.g. VAT number invalid, partner on the BMF list) |
| **YELLOW** | A source has `ERROR` or no result, or `REVIEW` | Not confirmed: information is missing, or a person must look |
| **GREEN** | Otherwise: every source is `OK` or `NOT_APPLICABLE` | No problems found |

- `NOT_APPLICABLE` (e.g. VIES for a partner without a VAT number) does not spoil a green result. If
  **no** source applies, the result is YELLOW ("Nothing could be checked"), never GREEN.
- `REVIEW` (e.g. a BMF match by name only) is YELLOW. The story text says "GREEN otherwise", but a
  possible match must never look like a clean result, so REVIEW is YELLOW by default (setting below).
- A source without any result counts as missing information: always YELLOW.
- Risk hints (E8) are not check results and never change the overall result.
- The Firmenbuch and GISA are only part of a run when their API key is set. If a partner has a
  company register number but one of them is not set up, the explanation says so ("The Firmenbuch is
  not set up on this server, so it was not checked.") and `not_checked` lists it. The level does not
  change, because the run could not ask that source at all; the result screen shows it as a
  "Not checked" card.
- The run is still `running`: no overall result yet (`overall: null`).

### Changing the rules

Each status can be set to another level in `.env`:

```
OVERALL_LEVEL_REVIEW=RED      # GREEN, YELLOW or RED
```

`FINDING` and `ERROR` can never be GREEN: the API does not start with such a setting, and it
does not start with a value that is not a level either.

## API

`GET /api/v1/runs/{run_id}` (and the start, `POST /api/v1/partners/{id}/runs`) has `overall`:

```json
"overall": {
  "level": "RED",
  "summary": "A problem was found by the BMF list. The HFU list could not be checked, so the result is not complete. Please check again later.",
  "reasons": [
    {"source": "VIES", "status": "OK", "level": "GREEN"},
    {"source": "BMF", "status": "FINDING", "level": "RED"},
    {"source": "HFU", "status": "ERROR", "level": "YELLOW"}
  ],
  "disclaimer": "This result is information only. ..."
}
```

`reasons` has every source of the run in order; `status` is `null` for a source without a result.
`not_checked` lists sources that apply to the partner but are not set up on the server (e.g.
`["FIRMENBUCH", "GISA"]`).

The partner endpoints (`GET /api/v1/partners`, `GET /api/v1/partners/{id}`) also have
`latest_overall` (`run_id`, `level`, `summary`, `finished_at`): the result of the partner's latest
finished run, or `null` if it was never checked in a run. The partner list shows it as a badge, also
after a reload.

The result is computed when the run is read, not stored, so it always follows the current rules.
The PDF report (S6.3) and the history (S6.2) can use the same function.

## Result screen

`/checks/{run_id}` (link "Open the full result" on the partner page, and the coloured badge in the
partner list, which shows each partner's latest result):

- The overall result at the top: icon **and** words ("Red: problem found"), never colour alone.
- One card per source with status, explanation, source, retrieval time and data age (how old the
  imported list was; live sources say "Live answer from the source").
- A negative result and missing information look different: a **problem** has a solid red border and
  a ✕ icon; **missing information** has a dashed amber border and a ? icon.
- The disclaimer: the result is information only, the decision stays with the customer. It is shown
  with every result: on the result screen (also while the sources are still being asked) and under the
  overall result on the partner page. The API sends it as `overall.disclaimer`.

## Code

| File | What |
|---|---|
| `backend/app/checks/overall.py` | Rules, explanation texts, disclaimer (pure Python) |
| `backend/app/checks/router.py` | `overall` in the run response |
| `backend/tests/test_overall_result.py` | Every combination of statuses, texts, settings |
| `frontend/src/components/overall-result.tsx` | Banner, badge, per-source card, disclaimer |
| `frontend/src/pages/CheckResultPage.tsx` | The result screen |
