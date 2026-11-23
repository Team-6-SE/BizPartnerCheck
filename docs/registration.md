# Self-registration of organisations (S2.2 / SCRUM-48)

A new customer registers on `/register` (linked from the landing page and the sign-in page). No one at our side
has to do anything.

- The language dropdown (English / Deutsch) sits where Keycloak's own one sits on the sign-in page. The choice is
  remembered in the browser and sent to Keycloak (`ui_locales`), so the sign-in page opens in the same language.
- "Already have an account? Sign in" goes straight to Keycloak's sign-in page, without a page of ours in between.

## Flow

1. The form sends company name, admin name, e-mail and optionally the organisation's VAT number to
   `POST /api/v1/registration` (public, no token).
2. The backend checks the input, creates the organisation in the database (not yet committed) and then, in Keycloak,
   the admin user with the attribute `organization_id`, the role `org-admin` and the required actions
   "verify e-mail" and "set password".
3. Keycloak sends one e-mail with a link. The admin confirms the address and sets a password there; "Back to
   application" leads to `APP_BASE_URL`. Before that the account has no password, so nobody can sign in with it.
4. At the first sign-in the admin sets up the second factor (all admins need one, see
   [security-log.md](security-log.md)).

## Together or not at all

The organisation is committed only after all Keycloak steps worked. If a Keycloak step or anything else fails, the
database change is rolled back and an already created Keycloak user is deleted again. The answer is then
`503 registration_unavailable` ("try again"), so there is never an organisation without admin or an admin without
organisation.

## Answers

| Case | Status | `detail.code` | Shown at |
|---|---|---|---|
| Registered, e-mail sent | 201 | – | success page |
| E-mail already registered | 409 | `email_already_registered` | e-mail field |
| VAT number already used by another organisation | 409 | `duplicate_organization_vat` | VAT field |
| Wrong VAT number format | 422 | `invalid_vat_format` | VAT field |
| Invalid e-mail address | 422 | `invalid_email` | e-mail field |
| Hidden "website" field filled (bot) | 400 | `registration_rejected` | form |
| More than 5 attempts per IP in 15 minutes | 429 | `registration_rate_limit` | form |
| Keycloak or mail server not reachable | 503 | `registration_unavailable` | form |

## Abuse protection (T2.2.4)

- Honeypot: a field that people do not see; bots fill it in.
- Rate limit: 5 attempts per IP address in 15 minutes, kept in memory of the backend process (reset on restart,
  separate per process). Behind Caddy the backend trusts `X-Forwarded-For` (`FORWARDED_ALLOW_IPS`), otherwise all
  visitors would share Caddy's address and block each other.
- Later, if needed: a CAPTCHA, or the limit in the database or in Caddy for several backend processes.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `KEYCLOAK_REGISTRATION_CLIENT_ID` | `bizpartnercheck-registration` | Keycloak client that may create users |
| `KEYCLOAK_REGISTRATION_CLIENT_SECRET` | local: secret from the realm file | Must be set on every server; without it registration answers 503 instead of using a known secret |
| `APP_BASE_URL` | `http://localhost:5173` | Address of the web app (link in the e-mail, allowed redirect URLs in the realm) |

Locally the e-mail lands in Mailpit: http://localhost:8025
