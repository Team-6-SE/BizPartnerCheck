# SCRUM-49: Organisation user and role management

## Roles and permissions

- **org-admin:** Invite and manage users in their organisation, and use partner/check workflows. The last active, email-verified organisation admin cannot be disabled, deleted or demoted (HTTP 409).
- **checker:** Create/update/archive partners and start checks; can read results. Cannot manage users.
- **reviewer:** Read partners, history and check results only; writes return HTTP 403.
- **platform-admin:** Platform operator, not an organisation-management role. Members holding this role are omitted from the organisation Users page and cannot be changed or deleted through its endpoints, even if they belong to the same organisation.

All user endpoints check the authenticated organisation. Cross-organisation users are reported as not found. The API rechecks an org-admin's live account and roles with Keycloak, and serialises last-admin mutations under a PostgreSQL advisory lock.

## Invitations

An organisation admin opens **Users**, chooses a role and invites by email. Keycloak creates the user, assigns the selected role and sends an invitation via `execute-actions-email`; the link expires after seven days. The user verifies their email and creates a password. Resend is allowed only before verification; verified accounts return 409. Locally, SMTP points to Mailpit at http://localhost:8025 and no public email is delivered.

## Local existing Keycloak installation

Keycloak's realm import applies to a **new realm**, not to an existing one. Never reset PostgreSQL or delete a realm just to add roles.

For an existing local realm, open Keycloak Admin Console → `bizpartnercheck` → **Realm roles** and create `checker` and `reviewer` (or use the existing `setup_local_keycloak_roles.sh` script). Under **Users**, find `demo@bizpartnercheck.local` → **Role mapping** → assign `checker` to restore demo access. Sign out and in to refresh the JWT.

For new environments the two roles and demo mapping come from `infra/keycloak/import/bizpartnercheck-realm.json`. For staging, add the two realm roles using an administrator account once; do not recreate or wipe the live realm.

## API endpoints

- `GET /api/v1/users` — list members, excluding platform admins
- `POST /api/v1/users/invitations` — invite by email, name and role
- `POST /api/v1/users/{id}/resend-invitation` — resend pending invitation
- `PATCH /api/v1/users/{id}/role` — change organisation role
- `PATCH /api/v1/users/{id}/status` — activate/deactivate
- `DELETE /api/v1/users/{id}` — permanently remove a manageable member

## Review checks

Run in `backend`: `uv run ruff check app tests`, `uv run ruff format --check app tests`, and `uv run pytest -q`. Run in `frontend`: `npm test -- --run`, `npm run lint`, `npm run build`. Then manually test an invitation in Mailpit and member removal with a non-admin test account. Avoid deleting the only organisation admin.
