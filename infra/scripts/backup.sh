#!/usr/bin/env bash
set -euo pipefail

# Daily backup of both databases (cron: scripts/backup.cron), kept for 14 days.
#   bizpartnercheck_<time>.dump  partners, checks, security log (service "db")
#   keycloak_<time>.dump         users, passwords, second factors (service "keycloak_db")
# Restore test: bash scripts/restore-test.sh <file>. Details: docs/deployment.md

# Run from the infra directory on the staging server.
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-/var/backups/bizpartnercheck}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

backup() {
  local service="$1" file="$2"
  docker compose --env-file deploy.env -f compose.deploy.yml exec -T "$service" \
    sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "$file"
  chmod 600 "$file"
  test -s "$file"
  echo "Backup created: $file"
}

backup db "$BACKUP_DIR/bizpartnercheck_$TIMESTAMP.dump"
backup keycloak_db "$BACKUP_DIR/keycloak_$TIMESTAMP.dump"

# Only after both backups worked: remove backups older than the retention time.
find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.dump' -mtime "+$RETENTION_DAYS" -print -delete
