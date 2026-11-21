# Firmenbuch check (S4.5)

## Context

Before doing business, a checker wants to know whether an Austrian partner really exists as a company and
is still active: not deleted, not insolvent, not in liquidation. The Firmenbuch (company register) is the
official source. Since 2025 its "High Value Datasets" (HVD) are free through JustizOnline, but only with an
API token after an approved IWG application (see [data-sources.md](data-sources.md)).

## Decision

**We ask the JustizOnline web service live** ("FBW-WebServices (HVD)", interface description v1.3 of
22.05.2025, SOAP 1.2) with one call per check: an extract (`AUSZUG_V2_REQUEST`) of the partner's company
register number (FN). The register changes daily, so we do not keep a copy.

- Endpoint: `https://justizonline.gv.at/jop/api/at.gv.justiz.fbw/ws` (WSDL: `.../ws/fbw.wsdl`)
- Headers: `X-API-KEY: <token>` and `Content-Type: application/soap+xml;charset=UTF-8`
- Over the rate limit the server answers HTTP `429`.

**Request** (`backend/app/adapters/firmenbuch.py`):

- `FNR` = the partner's FN as we store it, e.g. `123456a` (the service also writes `58468 h` with a space).
- `STICHTAG` = today in Vienna. A date in the future is refused ("Stichtag darf nicht in der Zukunft sein").
- `UMFANG` = `Kurzinformation`, the only extent HVD allows.

Partners without an FN (e.g. foreign partners) are not asked: `NOT_APPLICABLE` in a check run, `409
no_register_number` for the single check.

## Results

| Answer | Our result | Shown as |
|---|---|---|
| Company found, no flag | `OK` | "Registered" with name, address, legal form, seat, FN and persons |
| Deleted, insolvency or liquidation recorded | `FINDING` | "Flagged" and every flag with the register's own text and date |
| Only insolvency proceedings that have clearly ended ("Konkurs aufgehoben", ...) | `REVIEW` | "Please review" |
| A fault that clearly says there is no company with this FN | `FINDING` | "Not in register" (not the same as an error) |
| The service does not accept the FN ("Firmenbuchnummer ist ungültig!") | `ERROR` | "Error": please check the number |
| No API key, key refused (401/403), any other SOAP fault, an answer we do not understand (no XML, no `FIRMA`), not reachable, timeout, 429 | `ERROR` | "Error" with the reason; never OK |

**When in doubt: `ERROR`, not `FINDING`, and `FINDING`, not `REVIEW`.** A wrong "this company does not exist"
or a wrong flag on a healthy company is worse than "could not check"; an insolvency that is perhaps over is
still shown as a finding.

"Not found" is a SOAP fault whose text names the company or the number (Firma, Firmenbuchnummer, FNR, FN) **and**
says that it does not exist ("nicht gefunden", "nicht vorhanden", "existiert nicht", "keine Firma", ...), and
is not about our request (key, parameter, Stichtag). Everything else, e.g. "Unbekannter Fehler", is `ERROR`.
The interface description shows no example for this case, so the real text must be verified (below); until
then an unknown FN may come back as `ERROR` instead of "Not in register", which is the safe side.

"Firmenbuchnummer ist ungültig!" is the documented fault for a malformed number. It is an `ERROR`, not a
finding: if our format were wrong (point 4 below), every partner would get it.

Faults are read before the HTTP status, because SOAP faults usually come with HTTP 500. 429 and 5xx are asked
again (shared retries, [source-adapters.md](source-adapters.md)); a refused key or another fault is not.

### How the flags are found (UNVERIFIED)

Every legal fact (`RECHTSTATSACHE`) has a `CODE`, but the HVD interface does not list the codes. So for now we
read the German text of the current legal facts (`AUFRECHT` not `false`). **These rules follow the usual
register wording and are not verified with real extracts** (point 3 below); once the codes are known, we
match on them instead. The rules are strict on purpose:

- Whole words only, read clause by clause (split at `;`, line breaks and full stops that end a sentence).
- **Deleted**: a data group of the company carries `MIT_FIRMA_GELOESCHT_DURCH_VNR` (documented in the XSD), or
  a legal fact speaks of the deletion of the company: "Löschung" that is not "Löschung der/des/von
  *something else*" ("Löschung der Prokura" is not a flag), or "gelöscht" with Firma/Gesellschaft in the
  same clause.
- **Insolvency**: a word that starts with Konkurs, Insolvenz, Sanierungsverfahren, Schuldenregulierung,
  Ausgleichsverfahren or zahlungsunfähig.
- **Liquidation**: the words Liquidation, "in Liqu." or Abwicklung (not "Abwicklungsservice"); "Auflösung"
  with the same rule as "Löschung" ("Auflösung der Zweigniederlassung" is not a flag); "aufgelöst" with
  Firma/Gesellschaft in the same clause. In the **name** only "in Liquidation" / "in Liqu.", the suffix the
  law asks for during liquidation; other words in a name ("Müller Abwicklungsservice GmbH") are never flags.
- **Ended insolvency** (`REVIEW` instead of `FINDING`): only if every clause about the insolvency itself says
  it has ended (aufgehoben, Aufhebung, beendet, eingestellt, abgeschlossen, rechtskräftig bestätigt).
  "Konkurs eröffnet; Vertretungsbefugnis aufgehoben" stays a `FINDING` (the ending word belongs to another
  fact), and so does "... mangels Kostendeckung" (too little money even for the proceedings).

## Data minimisation (acceptance criterion 3)

The extract also contains birth dates, private addresses and citizenship of persons, and capital shares. We
do **not** store the XML. It is read with `defusedxml` (no entities, no DTD), as it comes from outside. We store only what the check needs, as JSON in `check_results.raw_response`:

- the company: name, business address, seat, legal form, deletion entry number;
- current legal facts: code, date, text (names and addresses inside them are not read);
- for every current function (managing director, shareholder, Prokurist, board member ...): the person's or
  company's **name, role and start date**. Ended functions are left out.
- evidence of the query: FN, reference date, query time and checksum (`PRUEFSUMME`) of the service.

The API returns these as `register_details` on Firmenbuch results (`found`, `register_number`, `legal_form`,
`seat`, `flags`, `persons`), plus `company_name` and `address`.

**Retention of the person names.** The names, roles and start dates are public register data and the evidence
for what the check showed (acceptance criterion 3), so they are kept with the check result and deleted with it.
We add no separate rule for them now: how long check results are kept is one decision for all sources and
belongs to the privacy concept (S9.x), like the retention of the security log.

## API key (secret)

The token comes from the JustizOnline profile ("Information Reuse") once the application is approved.

- Local: `FIRMENBUCH_API_KEY=...` in your own `.env` (not in git: `.env` is in `.gitignore`).
- Server: `FIRMENBUCH_API_KEY=...` in `deploy.env` only (backend and worker both get it via
  `infra/compose.deploy.yml`); `deploy.env` stays on the server and is in `.gitignore`, so it
  never goes into Git ([deployment.md](deployment.md)).
- Never in code, tests, issues, pull requests or the team chat. The key is only sent in the request header and
  never stored in a result.

**Without a key the Firmenbuch is not part of check runs** (otherwise every run would be incomplete). The API
logs a warning at startup. Once the key is set and the API and worker are restarted, runs ask VIES, BMF, HFU
and the Firmenbuch. The single check `POST /api/v1/partners/{id}/checks/firmenbuch` works without a key too and
stores `ERROR` ("not set up on this server yet").

| Setting | Meaning |
|---|---|
| `FIRMENBUCH_API_KEY` | Token from JustizOnline (secret). Empty: Firmenbuch not in runs |
| `FIRMENBUCH_ADAPTER` | `fake-ok`, `fake-finding` (insolvency), `fake-timeout`, `fake-malformed`: fake answers without network and key, also included in runs |
| `FIRMENBUCH_BASE_URL` | Another endpoint (default: production) |
| `FIRMENBUCH_TIMEOUT_SECONDS`, `..._MAX_RETRIES` | Time limits for this source only (default: the `SOURCE_...` values) |

## To verify when the key arrives

The adapter follows the interface description and the XSD; these points could only be assumed and must be
checked with a few real calls (e.g. a known active GmbH, a deleted company, a company in insolvency, a wrong
FN):

1. The exact fault text for an FN that does not exist (adjust `fault_kind` and its patterns if needed;
   until then such a check may end as `ERROR`).
2. Whether `Kurzinformation` contains the functions (`FUN`/`PER`) at all. The BMJ lists "vertretungsbefugte
   Organe" as HVD content, shareholders are not mentioned: then "owners" from acceptance criterion 3 cannot
   come from HVD (tell the product owner).
3. How deletion, insolvency and liquidation appear in a real extract: the legal fact **codes** (then match on
   them instead of the text) and texts. Keep real answers, without the persons' data, as test fixtures.
4. Whether the FN must be sent as `123456a` or `123456 a`.

Test with the fake first: `FIRMENBUCH_ADAPTER=fake-ok` or `fake-finding` in `.env`, restart the API, add a
partner with an FN and click **Check**.
