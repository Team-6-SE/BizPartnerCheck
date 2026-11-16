
#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="${1:?Usage: bash restore-test.sh /path/to/backup.dump}"

if [[ ! -s "$BACKUP_FILE" ]]; then
  echo "ERROR: Backup file not found or empty"
  exit 1
fi

CONTAINER="bizpartnercheck-restore-test-$$"

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d \
  --name "$CONTAINER" \
  --network none \
  --tmpfs /var/lib/postgresql/data:rw,size=1g \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  postgres:17 >/dev/null

echo "Waiting for test database..."
for i in $(seq 1 60); do
  if docker exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

docker exec "$CONTAINER" pg_isready -U postgres
docker cp "$BACKUP_FILE" "$CONTAINER:/tmp/backup.dump"

docker exec "$CONTAINER" createdb -U postgres restore_check
docker exec "$CONTAINER" pg_restore \
  -U postgres -d restore_check \
  --no-owner --no-acl --exit-on-error \
  /tmp/backup.dump

docker exec "$CONTAINER" psql -U postgres -d restore_check \
  -c "SELECT count(*) AS restored_tables FROM information_schema.tables WHERE table_schema = 'public';"

echo "Restore test completed successfully"
