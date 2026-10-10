# Runbook: credential rotation

**Alerts:** `AnalyticsLlmConfigurationError`. Also use this runbook on a schedule, when someone with
access leaves, after any suspected exposure, and when a secret appears in a log or a repository.

Every secret can be supplied as a file (`NAME_FILE=/path`) so it can be rotated without rebuilding an
image. A process reads its configuration once at startup, so **rotation takes effect when instances
restart**; a rolling restart keeps the service available.

| Secret | Setting | Who uses it | Rotation impact |
|---|---|---|---|
| Application database password (`app` role) | `DATABASE_URL`, `POSTGRES_PASSWORD` | backend, migrations, conversations, audit | restart backends |
| Analytics read-only password | `ANALYTICS_DATABASE_URL`, `ANALYTICS_DATABASE_PASSWORD` | backend analytics engine | restart backends |
| LLM API key | `GEMINI_API_KEY` | backend | restart backends |
| JWT signing key / public key | `JWT_SECRET` or `JWT_PUBLIC_KEY` | backend verifies tokens | existing tokens stop working |
| Metrics / operator token | `METRICS_TOKEN` | Prometheus scrape, diagnostics | update the scraper |

## Symptoms

- `LLM_CONFIGURATION_ERROR`, `LLM_CREDENTIALS_INVALID` or `LLM_MODEL_UNAVAILABLE` errors: the provider key is missing, expired,
  revoked, or the model name was retired. `/health/ready` shows `degraded: ["llm_provider"]` when
  the key is absent.
- Startup fails with `Invalid configuration:` and a list of setting names (never values).
- `DATABASE_UNAVAILABLE` after a password change that was not applied everywhere.

## Impact

During a correct rolling restart there is none. A wrong rotation shows as the symptoms above for the
affected feature only.

## Diagnose

1. `GET /api/v1/health/diagnostics` shows which dependency fails and the migration revision.
2. The startup error lists the setting names that are invalid or missing; fix those.
3. For `*_FILE` secrets, confirm the file exists, is non-empty, and is readable by the container's
   user; setting both `NAME` and `NAME_FILE` is a startup error by design.

## Mitigate

Rotate one secret at a time. For each: create the new value, make both old and new work if the
system allows it, roll the change, verify, then retire the old value.

### LLM API key

1. Create a new key in the provider console.
2. Update the secret store / mounted file (`GEMINI_API_KEY_FILE`).
3. Rolling restart the backends.
4. Verify (below), then delete the old key at the provider.

### Database passwords (`app` and `analytics_readonly`)

PostgreSQL role passwords are not changed by environment variables on an existing cluster.

1. Change the password in PostgreSQL: `ALTER ROLE analytics_readonly PASSWORD '<new>';`
   (and `app` for the application role). Existing connections keep working until they close.
2. Update the connection URLs in the secret store (percent-encode special characters).
3. Rolling restart the backends and run the one-shot migration job with the new `app` URL.
4. Run `make verify-permissions`.
5. Keep the two roles' passwords different from each other.

### JWT signing keys

Rotation invalidates tokens signed with the old key unless both are accepted.

1. Publish the new public key (RS256/ES256) or secret (HS256) to the verifier configuration.
2. Switch the issuer to sign with the new key.
3. Restart the backends; ask users to sign in again if you cannot overlap keys.
4. Remove the old key after the longest token lifetime has passed.

### Metrics / operator token

1. Generate a new token, update `METRICS_TOKEN_FILE` and Prometheus's `credentials_file`.
2. Restart backends, reload Prometheus, confirm `up{job="analytics-backend"} == 1`.

### After suspected exposure

Rotate immediately, treat the old value as public, and review the audit trail and provider usage for
the exposure window. Then follow [suspected-data-leak.md](suspected-data-leak.md).

## Verify recovery

- Backends start without `Invalid configuration:` and `GET /health/ready` is `ready`.
- `python scripts/smoke_test.py --base-url <url> --token <token>` passes.
- The provider console shows traffic on the new key and none on the old one before you delete it.
- `make verify-permissions` passes after database password changes.

## Follow-up

Record the rotation (date, secret, who). Schedule the next one. Add any secret that was found in the
wrong place to the repository's secret-scanning rules.
