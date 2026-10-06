#!/usr/bin/env bash
# Back up the application database to a compressed custom-format archive.
#
#   scripts/backup_postgres.sh                      # uses `docker compose exec postgres`
#   PGHOST=db.example.com PGUSER=app PGPASSWORD=... PGDATABASE=app scripts/backup_postgres.sh
#
# Output: backups/analytics-<UTC timestamp>.dump (pg_dump -Fc: compressed, restorable with
# pg_restore, selectively and in parallel). The archive contains personal data and credentials-
# adjacent configuration: store it encrypted, restrict access, and apply the same retention as the
# database. The analytics_readonly role is NOT part of a database dump; recreate it with
# database/init/01-analytics-role.sql after a restore into a fresh cluster.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT="${BACKUP_DIR}/analytics-${STAMP}.dump"
mkdir -p "${BACKUP_DIR}"
umask 077

if [[ -n "${PGHOST:-}" ]]; then
  pg_dump --format=custom --no-owner --no-privileges --file="${OUTPUT}" "${PGDATABASE:-app}"
else
  docker compose exec -T postgres pg_dump -U app -d app --format=custom --no-owner --no-privileges \
    > "${OUTPUT}"
fi

# A backup that cannot be listed is not a backup.
if [[ -n "${PGHOST:-}" ]]; then
  pg_restore --list "${OUTPUT}" > /dev/null
else
  docker compose exec -T postgres pg_restore --list < "${OUTPUT}" > /dev/null
fi
echo "backup written and verified: ${OUTPUT} ($(wc -c < "${OUTPUT}") bytes)"
