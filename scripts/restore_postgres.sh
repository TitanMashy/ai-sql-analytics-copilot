#!/usr/bin/env bash
# Restore a backup made by backup_postgres.sh into a database.
#
#   scripts/restore_postgres.sh backups/analytics-20261006T030000Z.dump [target_database]
#
# DESTRUCTIVE for the target: existing objects with the same names are dropped first
# (--clean --if-exists). The default target is a scratch database named app_restore_drill, so a
# drill can never touch the live `app` database by accident. Pass `app` explicitly, and stop the
# backend first, to restore for real. See docs/operations.md, "Backup and restore".
set -euo pipefail

DUMP="${1:?usage: restore_postgres.sh <dump file> [target database]}"
TARGET="${2:-app_restore_drill}"
[[ -f "${DUMP}" ]] || { echo "no such file: ${DUMP}" >&2; exit 2; }

if [[ "${TARGET}" == "app" && "${CONFIRM_RESTORE_LIVE:-}" != "yes" ]]; then
  echo "Refusing to restore over the live database 'app'." >&2
  echo "Stop the backend, then re-run with CONFIRM_RESTORE_LIVE=yes." >&2
  exit 3
fi

if [[ -n "${PGHOST:-}" ]]; then
  psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${TARGET}\"" 2>/dev/null || true
  pg_restore --clean --if-exists --no-owner --no-privileges --dbname="${TARGET}" "${DUMP}"
else
  docker compose exec -T postgres psql -U app -d postgres -c "CREATE DATABASE \"${TARGET}\"" \
    2>/dev/null || true
  docker compose exec -T postgres pg_restore -U app --clean --if-exists --no-owner --no-privileges \
    --dbname="${TARGET}" < "${DUMP}"
fi
echo "restored ${DUMP} into ${TARGET}"
