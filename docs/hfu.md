# ÖGK HFU list check (S4.4)

## Context

Clients of construction companies are liable for the contractor's unpaid social security contributions
(Auftraggeberhaftung, § 67a ASVG) unless the contractor is on the **HFU list** ("Liste der
haftungsfreistellenden Unternehmen") kept by the ÖGK Dienstleistungszentrum. Before paying, a checker wants
to know whether the partner is on the list. If it is not, the client may have to withhold part of the invoice
amount and pay it to the Dienstleistungszentrum. Interface: `docs/data-sources.md`.

## Decision

**Live query of the ÖGK web service** "AGH – Webservice HFU-Abfrage extern" version 3.0 (SOAP 1.1,
document/literal, free, no registration). No import: the service answers for a reference date, and the
list changes daily. The spike's alternative (a scheduled import like BMF, `docs/architecture.md` OI-01) is not
needed.

| | |
|---|---|
| Production | `https://www.sozialversicherung.at/agh-ws-prod/DienstgeberAbfrageWS_3_0` (`?wsdl` for the WSDL) |
| Test system | `https://www.sozialversicherung.at/agh-ws-tt/DienstgeberAbfrageWS_3_0` (fixed answers, see below) |
| Spec | [AGH_Anleitung_HFU_Abfrage_Webservice.pdf](https://www.sozialversicherung.at/agh-frontend-extern/resources/doc/AGH_Anleitung_HFU_Abfrage_Webservice.pdf) |

**Request** (`backend/app/adapters/hfu.py`, `build_request`): operation `dienstgeberAbfragen` with

- `uidAuftraggeber`: **our organisation's own VAT number** (page *Settings*, `organizations.vat_number`). The
  service needs exactly one identifier of the requester (DGNR, VSNR or UID) and logs it. Without it the check
  is not sent: the result is `ERROR` with "your organisation's own VAT number is not set".
- `stichtag`: the reference date, **today in Vienna** (the list is Austrian; at 23:30 UTC it is already the
  next day there).
- `auftragnehmerRQ/uidAuftragnehmer`: the partner's VAT number. Partners without one get `409 no_vat_number`,
  like VIES. (The service also accepts a DGNR or VSNR, which we do not have.)
- Two rules from the spec: all elements are namespace-qualified as in its sample request, and the HTTP request
  must **not** carry a `SOAPAction` header, or the server rejects it.

**How we read the answer**: one `auftragnehmerRS` per contractor with `hfuListeDgJN` (on the list as
employer) and `hfuListeEpuJN` (on the list as one-person company, EPU), each `J` or `N`; plus name, address,
Firmenbuch number, UID and a `hinweis`, when the ÖGK knows them.

| Answer | Our result | Shown as |
|---|---|---|
| `hfuListeDgJN` or `hfuListeEpuJN` = `J` | `OK` | "Listed": no withholding for contractor liability is needed |
| both `N` | `FINDING` | "Not listed": a withholding may apply to payments |
| SOAP fault (the service refused the request, e.g. a bad number) | `ERROR`, not retried | "rejected the request: …" |
| HTTP 5xx / 429 without a fault, timeout, not reachable | `ERROR`, retried within the limits | "try again later" |
| other HTTP errors, not XML, no entry, unknown flag | `ERROR` | "not confirmed" |
| organisation's own VAT number not set | `ERROR`, nothing sent | "set it in the organisation settings" |

Every explanation names the reference date ("as of 16 Nov 2026"), the partner's name as the ÖGK knows it,
and any `hinweis`. "Not listed" is worded carefully: not being on the list is **not proof of a problem**
(for example, firms with under three years of construction work cannot be on the list yet). `ERROR` never
counts as OK. `data_as_of` stays empty: the service answers live for the reference date, which is stored in
the raw answer as `stichtag`.

**What is stored**: one row in `check_results` per check (source `HFU`) with the parsed answer as JSONB:
`stichtag`, `requester`, `checked`, `auftragnehmerRS` (the service's own field names), or the error.

**API**:

- `POST /api/v1/partners/{id}/checks/hfu` – asks the ÖGK now, stores and returns the result (`201`;
  `ERROR` is a normal result). `404` unknown partner, `409` partner without VAT number.
- `GET /api/v1/partners` – each partner has `latest_hfu_check` (or `null`).

The web app runs it with "Check" after VIES and the BMF list and shows a third column.

**Configuration**:

| Variable | Default | Meaning |
|---|---|---|
| `HFU_BASE_URL` | production endpoint | e.g. the ÖGK test system or a stub for staging |
| `HFU_ADAPTER` | real | `fake-ok`, `fake-finding`, `fake-timeout`, `fake-malformed` (no network, marked `"fake": true`) |
| `HFU_TIMEOUT_SECONDS` … | shared limits | see `docs/source-adapters.md` |

**ÖGK test system**: fixed answers for `uidAuftragnehmer` `ATU12345678` (never listed), `ATU12345676` (listed
as employer for reference dates 1 Jul – 31 Aug 2014), `ATU12345675` (listed as EPU in the same period, with
two sole traders) and `ATU12345674`. Because we always send today's date, the test system answers "not
listed" for every number; use `HFU_ADAPTER=fake-ok` to see a listed partner.

## Why / Alternatives

- **Live query instead of an imported copy**: the ÖGK offers no full-list download, only the web service and a
  web client. The service is free and needs no registration, so a copy would only add an import job.
- **UID as requester and contractor identifier** instead of DGNR or VSNR: it is the one number we have for
  both sides; the organisation's own VAT number already exists for the VIES consultation number.
- **Today as reference date** instead of a date chosen by the user: the story asks whether the partner is
  on the list now; a historic date can come with a later story.
- **`xml.etree` with namespace-agnostic parsing** instead of a SOAP library: one operation, one request shape;
  the service mixes prefixes (`ns2`, `ns3`, none) in its answers, so we match local names only.
- **A missing own VAT number is an `ERROR` result**, like VIES `INVALID_REQUESTER_INFO`: it is stored with a
  clear hint instead of failing the request, so the history shows that the partner was not confirmed.

## Tests

- `tests/test_hfu_adapter.py`: the request (our UID, the partner's UID, Vienna date, no `SOAPAction`),
  listed as employer / EPU, not listed, notes, missing requester, SOAP fault, retries, timeouts, unclear
  answers, the fake adapter. Fake HTTP answers (`httpx.MockTransport`), no internet.
- `tests/test_hfu_checks.py`: the API route with a fake service, stored results, partner without VAT
  number, latest result in the partner list.
