# External data sources

Research from SCRUM-26 (state: 30.10.2026). Update this file when answers arrive.

## Summary

- **No registration needed:** VIES, BMF fake-company list, ÖGK HFU list (the HFU call still needs a requester ID)
- **Access request needed:** Firmenbuch HVD (application with ID Austria, approved by the Ministry of Justice) and GISA ´´stage 2 (API key via ID Austria)
- **Cost:** all five are free of charge. Firmenbuch is free only for the High Value Datasets; other Firmenbuch products are paid.
- **Biggest open risks:** the Firmenbuch approval time is unknown, and the ÖGK HFU service requires our own DGNR, VSNR or UID in every request.

## Overview

| Source | Access method | Registration | Test environment | Lim
| --- | --- | --- | --- | --- |
| VIES | REST (JSON) + SOAP | none | yes, test endpoint with fixed test numbers | rate limits not published; member-state outages |
| ÖGK HFU | SOAP v3.0 + web client | none found, but requester ID needed | yes, separate test endpoint | max 50 contractors per request |
| BMF | RSS feed + CSV download | none | not needed (public data) | none stated |
| Firmenbuch | API via JustizOnline (IWG) | application with ID Austria, BMJ approval, then token | not documented | not documented |
| GISA | SOAP interface, stage 1 or 2 | stage 1 none; stage 2 API key via ID Austria | not documented | single-entity lookups only; key valid 1 year |

## VIES

EU VAT number check. Open public service of the European Commission; no API key and no contract.

- Endpoints: `check-vat-number`, `check-vat-test-service`, `check-status` (shows which member states are available)
- REST: `https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number`; SOAP via `checkVatService.wsdl`
- Test numbers: 100 = valid, 200 = invalid; further codes simulate errors
- Optional: send our own VAT number to get a consultation number as proof of the check
- Limits: rate limits exist but are not published, and flooding gets blocked. Each national database can be down on its own (`MS_UNAVAILABLE`, `MS_MAX_CONCURRENT_REQ`), so plan for retries and caching.
- Docs: Swagger spec at `https://ec.europa.eu/assets/taxud/vow-information/swagger_publicVAT.yaml`

## ÖGK HFU list

Social insurance list (HFU). Public SOAP web service, free of charge.

- Service: "AGH – Webservice HFU-Abfrage extern", version 3.0
- Production: `https://www.sozialversicherung.at/agh-wsprod/DienstgeberAbfrageWS_3_0` (add `?wsdl` for the WSDL)
- Test: `https://www.sozialversicherung.at/agh-wstt/DienstgeberAbfrageWS_3_0`, with defined test data in the interface description
- Web client for manual checks: `agh.sozialversicherung.at`
- Registration: none mentioned in the interface description. Versions 1.1 and 2.0 were shut down after Q2 2023.
- Request: exactly one identifier of the client (DGNR, VSNR or UID) plus a reference date; up to 50 contractors per request, identified by DGNR, VSNR or UID
- Caveat for results: "not found" does not mean non-compliant (for example, firms with under three years of construction work cannot be on the list). The UI must word this carefully.

## BMF fake company list

Public list of fake companies (Scheinunternehmen) under § 8 SBBG. There is no query API, so we sync the list into our own database and search it locally.

- RSS 2.0 feed: `https://service.bmf.gv.at/service/allg/lsu/rss_lsu.asp`; the BMF page also offers a full CSV export
- Data per entry: name, address, Firmenbuch number, UID, date of birth for individuals, publication date, date the decision became final
- The feed is ISO-8859-1 encoded and the details sit in HTML inside each item's description, so parsing needs care
- Registration: none. Test environment: none; test against a saved copy of the feed.
- Proposal: load the CSV once for the full history, then poll the RSS feed daily for new entries

## Firmenbuch

Company register, High Value Datasets (HVD) via JustizOnline. Free since January 2025, but only after an approved application. Longest and least predictable lead time, so request it first.

- Access: API under the Information Reuse Act (IWG) via JustizOnline; the interface spec is a ZIP download on the BMJ site
- Registration: log in to JustizOnline with ID Austria and file an IWG application; the Ministry of Justice decides. After approval the token appears in the JustizOnline profile under "Information Reuse".
- Contract: the BMJ publishes a reuse agreement (§ 6 (3) 3 with § 10 IWG); check whether HVD-only use needs it signed
- Costs: HVD free; other products are priced under § 8 IWG. Manual extracts on JustizOnline cost EUR 4.89 to 8.20 each.
- Test environment and limits: not documented, to ask BMJ support
- To verify after approval: whether HVD includes managing directors and other officers

## GISA

Business licence register. Free public SOAP interface in two stages; we need stage 2.

- Stage 1: no authentication, basic data only, lookup by GISA number
- Stage 2: search by name, all public data including history and ended licences, officially signed extracts. Needs a personal API key.
- Key: obtained at `gisa.gv.at/sst-Neuausstellung` with ID Austria and acceptance of the terms. One valid key per person, expires after one year, a new key invalidates the old one.
- Logging: every query is logged for seven years, the people looked up may be told who queried them, and the key holder is personally responsible
- Limits: single person or business only (validation), no mass queries such as industry lists; no rate limit published
- Test environment: none documented
- Licence code table (Gewerbeschlüssel): open data as xlsx on data.gv.at
- Support: support@gisa.gv.at (technical, weekdays 8:00–15:30); gewerbe@bmwet.gv.at (terms of use)

## Access requests

| Source | What to request | Who | Status | Notes |
| --- | --- | --- | --- | --- |
| Firmenbuch HVD | IWG application on JustizOnline | TBD | Not started | File first; approval time unknown |
| GISA stage 2 | API key at gisa.gv.at | TBD | Not started | Key is personal, logged 7 years, expires after 1 year |
| VIES | nothing | – | Not needed | Use test endpoint for development |
| BMF list | nothing | – | Not needed | Public RSS + CSV |
| ÖGK HFU | nothing | – | Not needed | Needs a requester ID |
