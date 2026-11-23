# Partner directory (S3.2 / SCRUM-58)

Search, sorting, editing and archiving of partners, and the partner page.

## Search

`GET /api/v1/partners?search=…` finds a partner when the term is part of its company name, VAT number or company
register number (case does not matter).

- Numbers are stored normalised (`ATU12345678`, `123456a`), so the term is normalised the same way for those two
  columns: `atu 1234` finds `ATU12345678`, `FN 123456a` finds `123456a`.
- `%` and `_` are searched as characters, not as wildcards (`100%` finds "100% Bio GmbH", not every name with "100").
- Trigram indexes keep the search fast with many partners (migration `e3d033729051`).
- The web app waits 300 ms after the last key press, so typing sends one request instead of one per key.

## Sorting and pages

`sort_by` = `created_at` (default), `company_name`, `vat_number` or `company_register_number`; `sort_order` = `asc`
or `desc`. Partners without a value in the sort column come last in both directions. Another `sort_by` gives
`422 invalid_sort`. Pages have 20 partners (`page_size` up to 100). If the shown page no longer exists (e.g. its last
partner was archived), the web app jumps to the last page.

## Edit

Only the company name can be changed (`PATCH /api/v1/partners/{id}`). VAT and register number identify the partner
and are part of every stored check, so they are not edited; a wrong number means archiving the partner and adding it
again. Editing never changes stored check results.

## Archive and restore

- `PATCH …/archive` hides the partner from the list and from the count; `GET /api/v1/partners/archived` lists them.
  `PATCH …/restore` brings it back. Nothing is deleted, the check history stays.
- Archived partners cannot be checked: `409 partner_archived` (the partner exists, so not 404). Restore it first.

## Delete

`DELETE /api/v1/partners/{id}` → `204` removes the partner **and all its check runs and results**, for good. It is
for partners added by mistake; archiving is the way to keep the history.

- The web app asks first (dialog "Delete …?", Cancel has the focus). In the list it is a quiet trash icon next to
  Edit and Archive (red only when pointed at, tooltip "Delete partner"); on the partner page "Delete Partner".
- While a check of the partner is running: `409 check_running`; try again when it has finished.
- The security log keeps the deletion (`PARTNER_DELETED`: who, when, VAT and register number, number of results),
  so the evidence that a check happened is gone, but not the fact that someone deleted it.
- Same rights as archiving: every user of the organisation; another organisation's partner gives
  `404 partner_not_found` (`tests/test_partner_delete.py`).

## Partner page

`/partners/{id}` shows the identifiers, the latest result of every source (VIES with registered name, address and
consultation number; BMF list) and the full history, newest first (`GET …/checks`).

## Isolation

Every endpoint above only sees partners of the organisation in the sign-in token. A partner of another organisation
gives `404 partner_not_found` for reading, editing, archiving, restoring, checking and the history
(`tests/test_partner_directory.py`).
