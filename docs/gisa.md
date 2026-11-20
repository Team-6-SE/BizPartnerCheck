# GISA licence check (S4.6)

## Context

Many trades in Austria need a business licence (Gewerbeberechtigung). Before ordering work, a checker wants to
see which licences the partner holds, whether they are active, and who is responsible for them
(gewerberechtlicher Geschäftsführer). The official source is GISA, the business licence register of the
Ministry of Economy (BMWET). See [data-sources.md](data-sources.md) for the access conditions.

## Decision

**We ask the public GISA interface, version 2, live** (SOAP, free, needs a personal API key):

- Endpoint: `https://www.gisa.gv.at/gisa-svc-public/GisaPublicV2.svc/soap`
- WSDL: `https://www.gisa.gv.at/gisa-svc-public/GisaPublicV2.svc?SingleWSDL`
- Spec: [GISA Öffentliche Schnittstelle V2 (PDF)](https://www.bmwet.gv.at/dam/jcr:8202eee5-446d-4223-9344-a6055f57795f/GISA_Dokumantation_%C3%B6ffentliche%20Schnittstelle_v2.pdf),
  XML structure and SoapUI examples on the [BMWET GISA interface page](https://www.bmwet.gv.at/Themen/Unternehmen/GISA_Gewerbeinformationssystem/GISA_Schnittstelle.html)

Two steps per check (`backend/app/adapters/gisa.py`):

1. `SearchPersonJur` with `Apikey`, `Firmenbuchnummer` = the partner's FN and `SearchHistorisch=true`: every
   licence of the company, also ended ones, as GISA numbers.
2. `GetGewerbeV2` with `Apikey` and `GISAZahl` for each licence (at most 15): trade, key, dates, suspension,
   issuing authority, location and the responsible person.

Request format as in the ministry's SoapUI examples: namespace `http://gisa.wien.gv.at/public_svc/V2`,
`<v2:Operation><v2:input>` and the fields without namespace. Answers: `<OperationResult>` with `Returncode`
(`OK`/`ERROR`) and `MeldungListe/Meldung` (`Code`, `Beschreibung`), the data without namespace.

GISA is searched by FN, so partners without an FN (foreign companies, sole traders without register entry) get
`NOT_APPLICABLE` in a check run and `409 no_register_number` for the single check. A search by name would
find other companies with similar names, so we do not do it.

Limits from the spec: `GetGewerbeV2` 200 calls per key per minute; content errors ("not found") come as a
`Meldung` (Code, Beschreibung, Meldungsart) with HTTP 200, transport errors as HTTP 4xx/5xx.

**Time.** All calls of one check share the time of one attempt (`GISA_TIMEOUT_SECONDS`, default 8 s, within
the 30 s of a check run): the search first, then the details while time is left (current licences first).
Without this, a company with 15 licences could need 16 × 8 s and miss the run's time limit. Details that do
not fit are not asked (see the results below). Raise `GISA_TIMEOUT_SECONDS` if real answers are slow.

## Results

| Answer | Our result | Shown as |
|---|---|---|
| At least one active licence | `OK` | "Active licence" and the list of all licences |
| Licences, but none active (ended or ruhend) | `FINDING` | "No active licence" and the list |
| No licence at all: the search answers with an empty hit list (`<GewerbeListe/>`) | `FINDING` | "No licence" |
| Only licences whose status we cannot read (e.g. `GetGewerbeV2` answers Meldung 1000 "GISA-Zahl nicht gefunden" for a hit) | `REVIEW` | "Please review" |
| No licence known to be active, and the details of a current licence could not be read for a technical reason (HTTP 4xx/5xx, Meldung 310, timeout, no time left) | `ERROR` | "Error": please try again |
| No API key, key not found or expired (Meldung 300), missing fields (Meldung 1050), SOAP fault, an answer we do not understand (no XML, no hit list), not reachable, timeout, 429 | `ERROR` | "Error" with the reason |

**When in doubt: `ERROR`.** A wrong "this partner has no licence" is worse than "could not check". So "No
licence" needs GISA's hit list, even if it is empty: an answer without `<GewerbeListe>` is an error, not "no
licence". A licence whose details failed for a technical reason may well be active, so it makes the result
`ERROR` (asked again), unless another licence is already known to be active (`OK`) or the hit list already
shows that it has ended. Meldung 1000 is only defined for `GetGewerbeV2`; the search knows 300, 1030 and 1050.

Meldung 310 ("unexpected error"), 429 and 5xx are asked again (shared retries); a wrong key is not.

**State of a licence** (`licence_state`). GISA has no status field. Every part of a licence has its current
entry as a direct child (`<BerechtigungDaten><Berechtigung>`) and older or ended entries under `<Historie>`
(newest first). So:

- no current `<Berechtigung>`, only history → ended;
- `EndigungDatum` reached → ended;
- `Ruhend/IstRuhend = true` and `RuhendBis` not reached → suspended;
- `RechtswirksamAb` reached → active;
- otherwise (a search hit without detail, a licence starting in the future) → unknown.

The responsible person is the current `<GeschaeftsfuehrerDaten><Geschaeftsfuehrer>` of the licence itself (not
those of branches, tenants or continued operation), unless its `EndigungDatum` is reached.

Per licence the API returns (`licences` on GISA results): `gisa_number`, `trade`, `trade_key`, `state`,
`start`, `end`, `suspended_since`, `authority`, `location`, `manager_name`, `manager_since`. The partner page
lists them all; the partner list shows e.g. "2 licences, 1 active".

## Data minimisation

For persons we keep only the name (owner, responsible person) and the start date of the responsible person.
Birth dates (`GebDatum`) and GISA person IDs are not read. The XML is not stored; it is read with `defusedxml`
(no entities, no DTD), as it comes from outside.

**Retention of the names.** They are public register data and the evidence for what the check showed, so they
are kept with the check result and deleted with it. How long check results are kept is one decision for all
sources, in the privacy concept (S9.x), as for the Firmenbuch ([firmenbuch.md](firmenbuch.md)).

## API key (secret, personal)

- Get it at <https://www.gisa.gv.at/sst-Neuausstellung> with ID Austria; it is issued at once.
- The key belongs to **one person**: every query is logged for seven years under that person's name, and the
  people looked up may learn who asked. Use it only for real partner checks, never for mass queries.
- One valid key per person; it **expires after one year**, and a new key makes the old one invalid.
- Local: `GISA_API_KEY=...` in your own `.env`. Server: only in `deploy.env`. Never in git, issues or chat.

**Without a key GISA is not part of check runs** (like the Firmenbuch); the API logs a warning at startup.

| Setting | Meaning |
|---|---|
| `GISA_API_KEY` | Personal key from gisa.gv.at (secret). Empty: GISA not in runs |
| `GISA_ADAPTER` | `fake-ok` (one active, one suspended licence), `fake-finding` (no active licence), `fake-timeout`, `fake-malformed` |
| `GISA_BASE_URL` | Another endpoint (default: production) |
| `GISA_TIMEOUT_SECONDS`, `GISA_MAX_RETRIES` | Time limits for this source only |

## Checked with the real service

The element names, the request format and the error answers follow the ministry's XML structure file and
SoapUI examples; the tests use answers built the same way. Real calls (November 2026, FN of a large Austrian
company) confirmed:

- `SOAPAction` is `http://gisa.wien.gv.at/public_svc/V2/IGisaPublic/<Operation>` (from the WSDL).
- The input fields have no namespace and must be in the WSDL order (`Apikey` first, then alphabetical),
  otherwise the service ignores them.
- Our FN form `123456a` is accepted; GISA itself writes it with six digits (`0123456a`).
- With `SearchHistorisch=true` the hit list contains ended licences too, with the trade only under
  `<Historie>`. So the hit list already shows which licences ended; current ones are asked in detail first.
- A wrong key gives `Returncode ERROR` with `Meldung 300`.

Still to verify with a few real calls:

1. The answer for an FN without any licence. We expect an empty `<GewerbeListe/>` ("No licence"); if GISA
   leaves the list out, such a check ends as `ERROR` until `parse_search` is adjusted.
2. What GISA answers when the quota (200 `GetGewerbeV2` calls per minute) is exceeded: HTTP 429 (asked
   again) or a `Meldung` (then add its code to the temporary errors).
3. How long the calls take for a company with many licences (`GISA_TIMEOUT_SECONDS`).

Test with the fake first: `GISA_ADAPTER=fake-ok` or `fake-finding` in `.env`, restart the API, add a partner
with an FN and click **Check**.
