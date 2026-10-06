# Restore drill: YYYY-MM-DD

| | |
|---|---|
| Environment | staging / production-copy |
| Run by | |
| Database version | |
| Backup file and size | |
| Time to restore | |
| Result | PASSED / FAILED |

## Command and output

```
scripts/restore_drill.sh
<paste the printed record>
```

## Verification beyond row counts

- [ ] `alembic upgrade head` is a no-op on the restored database.
- [ ] `database/init/01-analytics-role.sql` and `make verify-permissions` pass against it.
- [ ] The backend started against the restored copy and `scripts/smoke_test.py` passed.

## Findings and actions

| Finding | Action | Owner | Done |
|---|---|---|---|
| | | | |
