# Drills

Backups, rollbacks, and rotations that have never been exercised are assumptions. This directory is
where each drill is recorded, so the evidence that they work (or the discovery that they do not) is
kept with the code.

| Drill | How | Cadence | Record |
|---|---|---|---|
| Restore from backup | `scripts/restore_drill.sh` | quarterly, and after a database upgrade | [restore-drill-template.md](restore-drill-template.md) |
| Rollback | deploy version N, then N-1 in staging, run `scripts/smoke_test.py` | quarterly, and before the first production release | copy the template, change the title |
| Credential rotation | follow [credential-rotation](../runbooks/credential-rotation.md) for one secret | per the rotation schedule | copy the template |
| Tabletop exercise | walk a team through a runbook with a scenario, no systems touched | when a runbook changes | copy the template |

Name each record `YYYY-MM-DD-<drill>.md`. A failed drill is a finding, not an embarrassment: record
it, fix the cause, and repeat the drill.

## Drills recorded so far

None yet. The first restore drill and the first rollback rehearsal are part of the Sprint 12
acceptance criteria and must be recorded here after they are run against a real environment.
