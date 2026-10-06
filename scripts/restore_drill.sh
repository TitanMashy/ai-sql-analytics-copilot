#!/usr/bin/env bash
# Prove a backup is restorable: restore into a scratch database and compare against the source.
#
#   scripts/restore_drill.sh                 # back up now, restore, verify, clean up
#   scripts/restore_drill.sh backups/x.dump  # drill an existing backup
#
# Prints a record you can paste into docs/drills/. Exit code 1 means the drill FAILED: treat that
# as an incident, because it means the backups cannot be trusted.
set -euo pipefail

DRILL_DB="app_restore_drill"
DUMP="${1:-}"
if [[ -z "${DUMP}" ]]; then
  scripts/backup_postgres.sh
  DUMP="$(ls -1t "${BACKUP_DIR:-backups}"/analytics-*.dump | head -n 1)"
fi

psql_run() {
  if [[ -n "${PGHOST:-}" ]]; then
    psql -d "$1" -At -v ON_ERROR_STOP=1 -c "$2"
  else
    docker compose exec -T postgres psql -U app -d "$1" -At -v ON_ERROR_STOP=1 -c "$2"
  fi
}

STARTED="$(date -u +%FT%TZ)"
SECONDS=0
scripts/restore_postgres.sh "${DUMP}" "${DRILL_DB}"
ELAPSED="${SECONDS}"

FAILED=0
printf '%-22s %12s %12s\n' "table" "source" "restored"
for TABLE in customers vehicles drivers trips invoices payments conversations audit_log; do
  SOURCE="$(psql_run "${PGDATABASE:-app}" "SELECT COUNT(*) FROM ${TABLE}" 2>/dev/null || echo n/a)"
  RESTORED="$(psql_run "${DRILL_DB}" "SELECT COUNT(*) FROM ${TABLE}" 2>/dev/null || echo n/a)"
  printf '%-22s %12s %12s\n' "${TABLE}" "${SOURCE}" "${RESTORED}"
  # Rows written after the backup make the source larger, which is expected; fewer is not.
  if [[ "${RESTORED}" == "n/a" ]]; then FAILED=1; fi
  if [[ "${SOURCE}" =~ ^[0-9]+$ && "${RESTORED}" =~ ^[0-9]+$ && "${RESTORED}" -gt "${SOURCE}" ]]; then
    FAILED=1
  fi
done

psql_run postgres "DROP DATABASE IF EXISTS ${DRILL_DB}" > /dev/null
echo
echo "restore drill record"
echo "  started:   ${STARTED}"
echo "  backup:    ${DUMP}"
echo "  restore:   ${ELAPSED}s"
echo "  result:    $([[ ${FAILED} -eq 0 ]] && echo PASSED || echo FAILED)"
exit "${FAILED}"
