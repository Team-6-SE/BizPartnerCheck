
#!/usr/bin/env bash
set -euo pipefail

# Run from the infra directory on the staging server.
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-/var/backups/bizpartnercheck}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_FILE="$BACKUP_DIR/bizpartnercheck_$TIMESTAMP.dump"

docker compose --env-file deploy.env -f compose.deploy.yml exec -T db \
  sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$BACKUP_FILE"

chmod 600 "$BACKUP_FILE"
test -s "$BACKUP_FILE"
echo "Backup created successfully"
