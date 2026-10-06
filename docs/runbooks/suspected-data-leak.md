# Runbook: suspected data leak or boundary bypass

**Alerts:** `AnalyticsSecurityRejectionsSpike`, `AnalyticsDatabasePermissionDenied`. Also use this
runbook for any report that a user saw another customer's data, personal data (emails, phone
numbers, licence numbers, contact names), or internal system information.

Treat every report as real until disproven. Preserve evidence before changing anything.

## Symptoms

- A burst of `QUERY_SECURITY_ERROR` rejections: someone is probing with prompt-injection questions
  ("ignore previous instructions...", "list every email", "use set_config...").
- `QUERY_PERMISSION_ERROR` from the database: the validator allowed a statement that the database
  refused. That should never happen; it means the privilege model and the validator disagree.
- A user, support ticket, or customer reports data that should not be visible to them.
- An evaluation run reports `adversarial_leaks > 0`.

## Impact

Potential exposure of other tenants' data or personal data. Exposure paths that exist by design are
closed in layers: the validator, the database views (no personal columns, rows filtered to the
caller's tenant), and read-only transactions. A leak therefore means at least one layer failed.

## Diagnose

1. **Contain first, then investigate.** If exposure is plausible and ongoing, restrict access before
   debugging: set `AUTH_MODE` credentials to be revoked at the identity provider for the principal,
   or scale the backend to zero / block `/api/v1/analytics/ask` at the ingress.
2. **Find the request.** From the report you have a time, a user, or a request id ("Reference: ...").
   The audit trail holds every `/ask`:
   ```sql
   SELECT occurred_at, request_id, principal, customer_id, sql_hash, tables, row_count, outcome, error_code
   FROM audit_log
   WHERE request_id = '<id>' OR (principal = '<principal>' AND occurred_at > now() - interval '24 hours')
   ORDER BY occurred_at;
   ```
   The audit trail stores no question or SQL text by design. The `http request completed` log line for
   the same `request_id` shows timings and status. To see the SQL itself, reproduce with the same
   question in a non-production environment.
3. **Check the tenant boundary directly** (integration tests do this, run them against the
   affected environment): `pytest -m integration backend/tests/test_readonly_permissions.py`.
   Also verify privileges: `make verify-permissions`.
4. **Check the views.** From a database administrator account:
   ```sql
   SELECT table_name, column_name FROM information_schema.columns
   WHERE table_schema = 'analytics'
     AND column_name IN ('email', 'phone', 'license_number', 'name');
   ```
   This must return no rows for the `customers`, `users`, and `drivers` views. Confirm
   `analytics_readonly` has no privileges on `public` tables (`database/verify-readonly.sql`).
5. **Probing vs bypass.** `QUERY_SECURITY_ERROR` rejections alone are the validator working. Escalate
   to a bypass investigation only when a probing session was followed by `outcome = success` rows from
   the same principal with unusual tables or row counts, or when the permission-denied alert fires.
6. **Evaluation:** run the adversarial cases against the deployed provider:
   `python -m evals.run_eval --provider <mode> --ids adversarial-01,adversarial-02,...`.

## Mitigate

- **Credentials:** revoke the principal's tokens and rotate signing keys if a token may be stolen
  (see [credential-rotation.md](credential-rotation.md)).
- **Probing:** nothing to fix in the service; block or rate-limit the client and keep the alert.
- **Confirmed layer failure:** fix and release the failing layer (validator rule, view definition, or
  grant), add a regression test (a fuzz case, an integration case, or an evaluation case), and
  re-run the full suite plus `make verify-permissions` before restoring access.
- **Confirmed exposure of personal or customer data:** follow your breach-notification process:
  legal and privacy teams decide on notification. This runbook covers containment and evidence only.

## Verify recovery

- `pytest -m integration` and the adversarial evaluation cases pass; `make verify-permissions` passes.
- `QUERY_PERMISSION_ERROR` count is zero for 24 hours.
- The affected principal's access is intentionally restored (or revoked).

## Follow-up

Write the incident review: timeline, which layer failed, why detection took as long as it did, and
what permanent test or alert now covers it. Update `docs/threat-model.md` if the attack path was new.
