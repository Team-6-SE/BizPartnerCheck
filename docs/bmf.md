# BMF fake-company list check (S4.3)

## Context

The Austrian Ministry of Finance (BMF) publishes the list of companies that were found to be fake companies
(Scheinunternehmen, § 8 SBBG). A partner on this list must not be contracted. There is **no query API**, so we
keep our own copy of the list and compare partners with it (see `docs/data-sources.md`).

## Decision

### Source and import (T4.3.1)

- **Feed:** `https://service.bmf.gv.at/service/allg/lsu/rss_lsu.asp` (RSS 2.0, ISO-8859-1). It holds the
  **whole list** (about 1,700 entries since 2016), so the separate CSV export is not needed.
- Each entry: name, address, publication date, "Zeitpunkt als Scheinunternehmen", "Rechtskraft Bescheid",
  date of birth (individuals), Firmenbuch number, UID and Kennziffer des Unternehmensregisters. Except name and
  publication date, every field can be missing; the parser (`backend/app/bmf/feed.py`) handles that.
- **Tables:** `bmf_list_entries` (the list) and `bmf_imports` (history of every run).
- **Idempotent:** an entry is identified by a fingerprint of its content (the name alone is not unique), so
  importing the same feed again adds nothing. Entries are **never deleted**: an entry that is no longer in the feed
  gets `removed_at` and is not matched any more; if it comes back, `removed_at` is cleared.
- **A failed import never changes the list.** The old copy stays and its age shows in every result, if the feed
  - cannot be downloaded,
  - is not valid RSS or has no entries,
  - has fewer than half of our current entries (looks incomplete).
- Only one import runs at a time (PostgreSQL advisory lock), also with several API workers.

### Schedule and manual import (T4.3.2)

- The API imports the list **every 6 hours** in the background (`backend/app/bmf/background.py`), well within the
  required 24 hours, so one or two failed runs do not make the list too old. After a failure it tries again
  after 15 minutes. After a restart it only imports when the last successful import is older than the interval.
- **Platform admin** (new Keycloak role `platform-admin`):
  - `GET /api/v1/admin/bmf/status`: last successful import, last import (also failed ones), entries on the list
  - `POST /api/v1/admin/bmf/import`: import now; the result is in the response and in the history
  - Other users, including organisation admins, get `403`.
  - Locally `admin@bizpartnercheck.local` has the role. Recreate Keycloak once to get it:
    `docker compose -f infra/docker-compose.yml up -d --force-recreate keycloak`.

### Matching (T4.3.3)

`POST /api/v1/partners/{id}/checks/bmf` compares the partner with the active entries
(`backend/app/adapters/bmf.py`, built on the common framework, `docs/source-adapters.md`):

| Match | Status | Shown as |
|---|---|---|
| same VAT number (UID or Kennziffer des UR), or same Firmenbuch number | `FINDING` | "Listed", with the entry and its publication date |
| only the same company name | `REVIEW` | "Possible match – please review", **never OK** |
| nothing | `OK` | "Not listed" |
| the list was never imported | `ERROR` | "not confirmed" |

- **Name:** the partner has no name field yet, so we use the registered name from the latest valid **VIES**
  check. The web app therefore runs VIES first, then BMF. Names from fake VIES answers are never used. Without a
  name only the VAT number is compared, and the result says so.
- Names are compared after normalising (`backend/app/bmf/names.py`): lower case, umlauts (ä → ae), `&` → "und",
  no punctuation, no legal form at the end (GmbH, Ges.m.b.H., KG, OG, e.U., s.r.o., …) and no "in Liquidation".
  `MUSTER-BAU GES.M.B.H.` and `Muster Bau GmbH` match; `Muster Bau Wien GmbH` does not. There is no fuzzy matching,
  so similar but different names do not produce false alarms.
- **Firmenbuch number:** matched as soon as partners have one (S3.1, SCRUM-30).

### Result and freshness (T4.3.4)

- Every result stores the matched entry (name, address, numbers, publication date, dates of the decision) and
  `data_as_of` = time of the last successful import.
- If the list was **older than 24 hours** at the time of the check, the explanation ends with a warning and the
  web app shows "List as of … (older than 24 hours)" in amber. The status itself is kept.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `BMF_IMPORT_INTERVAL_SECONDS` | `21600` (6 h) | how often the list is imported; `0` = off |
| `BMF_FEED_URL` | the BMF feed | e.g. a saved copy for staging or demos |
| `BMF_ADAPTER` | real | `fake-ok`, `fake-finding`, … (no database needed, results marked `"fake": true`) |

## Why / Alternatives

- **RSS instead of the CSV export:** the feed already contains the full list and is the documented machine-readable
  form; one format means one parser.
- **Import into our database instead of asking BMF for every check:** there is no query API, and a local copy also
  works when the BMF site is down; the data age is always shown.
- **Fingerprint instead of the BMF link or name as key:** the same name appears more than once on the list.
- **Exact normalised name instead of fuzzy matching:** a fuzzy match would mark many honest companies; S4.3 only
  asks for "possible match" when the name matches.
- **Name from VIES instead of a name field on the partner:** no partner name exists yet; this can switch to the
  partner's own name once S3.2 adds one.

## Tests

- `tests/test_bmf_feed.py`: parser with `tests/fixtures/bmf_feed_sample.xml` (a short feed in the real format,
  made-up companies), number and name normalising.
- `tests/test_bmf_import.py`: first import, idempotent re-import, removed and returning entries, failed imports keep
  the list, history, schedule.
- `tests/test_bmf_checks.py`: VAT, Kennziffer and name matches, no match, never imported, data age and 24-hour
  warning, platform admin routes and permissions, fake adapter.
