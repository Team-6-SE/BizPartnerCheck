# HFU list check (S4.4)

## Context

Clients of construction companies are liable for the contractor's unpaid social security contributions
(Auftraggeberhaftung, § 67a ASVG), unless the contractor is on the **HFU list** of the ÖGK. Before paying, a
checker wants to know whether the partner is on the list. If it is not, a withholding may apply to payments.

## Decision

**We ask the ÖGK web service live** ("AGH – Webservice HFU-Abfrage extern" 3.0, SOAP, free, no registration).
The list changes daily and there is no download of the whole list, so an import like BMF makes no sense.

- Production: `https://www.sozialversicherung.at/agh-ws-prod/DienstgeberAbfrageWS_3_0` (`?wsdl` for the WSDL)
- Test system: `https://www.sozialversicherung.at/agh-ws-tt/DienstgeberAbfrageWS_3_0` (fixed answers for test numbers)
- Spec: [AGH_Anleitung_HFU_Abfrage_Webservice.pdf](https://www.sozialversicherung.at/agh-frontend-extern/resources/doc/AGH_Anleitung_HFU_Abfrage_Webservice.pdf)

**Request** (`backend/app/adapters/hfu.py`): one SOAP call `dienstgeberAbfragen` with

- `uidAuftraggeber` = **our organisation's own VAT number** (page *Settings*). The service needs exactly one
  identifier of the requester and logs it. Without it nothing is sent and the result is `ERROR` with a hint.
- `stichtag` = today in Vienna (the list is Austrian; at 23:30 UTC it is already the next day there).
- `auftragnehmerRQ/uidAuftragnehmer` = the partner's VAT number. Partners without one get `409 no_vat_number`.
- No `SOAPAction` header: the server rejects requests that carry one.

**How we read the answer.** One `auftragnehmerRS` per partner with `hfuListeDgJN` (on the list as employer)
and `hfuListeEpuJN` (on the list as one-person company), each `J` or `N`; plus name, address, Firmenbuch
number, UID and a `hinweis` when the ÖGK knows them.

| Answer | Our result | Shown as |
|---|---|---|
| one of the flags is `J` | `OK` | "Listed": no withholding for contractor liability is needed |
| both `N` | `FINDING` | "Not listed": a withholding may apply to payments |
| SOAP fault (the service refused the request) | `ERROR`, not retried | "rejected the request: …" |
| HTTP 5xx / 429, timeout, not reachable | `ERROR`, retried | "try again later" |
| other HTTP errors, not XML, no entry, unknown flag | `ERROR` | "not confirmed" |
| organisation's own VAT number not set | `ERROR`, nothing sent | "set it in the organisation settings" |

Every message names the reference date ("as of 16 Nov 2026"). "Not listed" also says that it is **not proof of
a problem** (young firms cannot be on the list yet), as the data-source spike warned. `ERROR` never counts as
OK. `data_as_of` stays empty (live source); the reference date is in the raw answer as `stichtag`.

**API:**

- `POST /api/v1/partners/{id}/checks/hfu` – asks the ÖGK now, stores and returns the result (`201`; `ERROR`
  is a normal result). `404` unknown partner, `409` partner without VAT number.
- `GET /api/v1/partners` – each partner has `latest_hfu_check` (or `null`).

The web app runs it with "Check" after VIES and BMF and shows an "HFU list" column.

**Configuration:** `HFU_BASE_URL` (optional, e.g. the ÖGK test system), `HFU_ADAPTER=fake-ok` (or
`fake-finding`, `fake-timeout`, `fake-malformed`) for a fake without network. The ÖGK test system lists its
test numbers only for reference dates in 2014, and we always send today, so use `fake-ok` to see a listed
partner.

## Why / Alternatives

- **Live query instead of a copy:** there is no full-list download, only the service and a web client.
- **VAT numbers as identifiers:** the service also takes DGNR or VSNR, but the VAT number is the one number we
  have for both sides, and the organisation's own VAT number already exists for the VIES consultation number.
- **Today as reference date:** the story asks whether the partner is on the list now.
- **`xml.etree` instead of a SOAP library:** one operation, one request shape. The answers mix namespace
  prefixes, so we match tag names without them.

## Tests

`tests/test_hfu_adapter.py` uses fake SOAP answers (`httpx.MockTransport`): the request, listed / not listed,
notes, missing requester, SOAP fault, retries, timeouts, unclear answers, the fake adapter.
`tests/test_hfu_checks.py` replaces the service with a fake in the API. No test needs the internet.
