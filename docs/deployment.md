# Deployment (staging) — S1.3 / SCRUM-37

How the app runs on the test server, which settings it needs, and how backups are made and restored.

## Overview

```
Internet ──443──► Caddy ─┬─ /api/*  ──► backend (FastAPI, port 8000) ──► db (PostgreSQL 17)
        (80 → 443)       ├─ other   ──► frontend (nginx with the built React app)
                         └─ AUTH_DOMAIN ──► keycloak (port 8080) ──► keycloak_db (PostgreSQL 17)
```

- Files on the server: the contents of `infra/` in `/opt/bizpartnercheck` (`compose.deploy.yml`, `Caddyfile`,
  `keycloak/`, `scripts/`) plus `deploy.env` (secrets, never in Git).
- Caddy gets the TLS certificates itself, redirects HTTP to HTTPS and only allows TLS 1.2 and 1.3.
- The backend runs `alembic upgrade head` before every start, so migrations are part of every deployment.
- Images are built by `.github/workflows/deploy.yml` and pushed to GHCR (`…-backend:staging`, `…-frontend:staging`).
  The workflow is started by hand (Actions → Deploy to Staging → Run workflow) until the server exists; then add
  `push: branches: [main]` again for automatic deployments.

## Settings

All variables are listed in `infra/deploy.env.example`. Copy it to `deploy.env` on the server and fill in real values.

| Variable | What for |
|---|---|
| `DOMAIN`, `AUTH_DOMAIN` | Host names of the app and of Keycloak (DNS must point to the server) |
| `POSTGRES_*`, `DATABASE_URL` | App database (same password in both) |
| `KEYCLOAK_DB_PASSWORD`, `KEYCLOAK_ADMIN_USER/PASSWORD` | Keycloak database and the first Keycloak admin |
| `OIDC_ISSUER`, `OIDC_JWKS_URL` | `https://<AUTH_DOMAIN>/realms/bizpartnercheck` (+ `/protocol/openid-connect/certs`) |
| `KEYCLOAK_API_CLIENT_SECRET` | Client that reads sign-in events for the security log |
| `KEYCLOAK_REGISTRATION_CLIENT_SECRET` | Client that creates the first admin at self-registration |
| `SMTP_*` | Mail server for Keycloak e-mails (registration link, password reset) |

GitHub (repository settings): secrets `STAGING_HOST`, `STAGING_USER`, `STAGING_SSH_KEY`, `STAGING_SSH_FINGERPRINT`
and the variable `AUTH_DOMAIN` (it is built into the frontend as `VITE_OIDC_AUTHORITY`).

### One realm file for local and staging

`infra/keycloak/import/bizpartnercheck-realm.json` contains placeholders like
`${APP_BASE_URL:http://localhost:5173}`. Keycloak fills them from its environment when it imports the realm; without
the variable the value after `:` is used. So locally nothing changes, and on staging the redirect URLs, the two
client secrets and the mail server come from `deploy.env`. No secret that is valid on the server is in Git.

Keycloak imports the realm only on its **first** start (`--import-realm` skips an existing realm). Later changes to
the JSON file have to be made in the admin console as well (or the realm is deleted and imported again).

### After the first start

The realm file also creates the local demo users (`demo@…`, `admin@…`) whose passwords are in the README. On a
server that anyone can reach they must not stay:

```bash
cd /opt/bizpartnercheck
docker compose --env-file deploy.env -f compose.deploy.yml exec keycloak sh -c '
  /opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master \
    --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" &&
  for u in demo@bizpartnercheck.local admin@bizpartnercheck.local; do
    id=$(/opt/keycloak/bin/kcadm.sh get users -r bizpartnercheck -q username=$u --fields id --format csv --noquotes)
    [ -n "$id" ] && /opt/keycloak/bin/kcadm.sh delete users/$id -r bizpartnercheck
  done'
```

Real customers then register themselves (`/register`, see [authentication.md](authentication.md)).

## Backups (T1.3.5)

`scripts/backup.sh` dumps both databases (`bizpartnercheck_<time>.dump` and `keycloak_<time>.dump`, PostgreSQL custom
format) to `/var/backups/bizpartnercheck` and deletes dumps older than 14 days (`RETENTION_DAYS`). Install the daily
run at 02:00 with:

```bash
sudo crontab -l 2>/dev/null | cat - /opt/bizpartnercheck/scripts/backup.cron | sudo crontab -
```

### Restore test

`scripts/restore-test.sh <file>` restores a dump into a throw-away PostgreSQL container without network and prints
the number of restored tables. Run it once after setting up the server and after changes to the database, e.g.:

```bash
bash scripts/restore-test.sh "$(ls -t /var/backups/bizpartnercheck/bizpartnercheck_*.dump | head -1)"
```

### Real restore (data loss on the server)

```bash
cd /opt/bizpartnercheck
docker compose --env-file deploy.env -f compose.deploy.yml stop backend
docker compose --env-file deploy.env -f compose.deploy.yml exec -T db \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < /var/backups/bizpartnercheck/bizpartnercheck_<time>.dump
docker compose --env-file deploy.env -f compose.deploy.yml start backend
```

For Keycloak the same with the service `keycloak_db` (stop `keycloak` instead of `backend`).

## Open points

- Rollback: every image is also tagged with its commit SHA. To go back, set that tag instead of `staging` in
  `compose.deploy.yml` on the server and run `docker compose … up -d` (a database migration is not undone by this).
- Production: same setup with its own server, domain and `deploy.env` (S1.3 asks for staging first).
