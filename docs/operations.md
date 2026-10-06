# Operations guide

How to deploy, scale, configure, observe, secure, back up, release, and recover the service. For
local development see the README; for the settings reference see [deployment.md](deployment.md).

## Contents

- [Components](#components)
- [Fresh-environment walkthrough](#fresh-environment-walkthrough)
- [Health and probes](#health-and-probes)
- [Migrations](#migrations)
- [Scaling](#scaling)
- [Secrets and rotation](#secrets-and-rotation)
- [Observability](#observability)
- [Backup and restore](#backup-and-restore)
- [Retention](#retention)
- [Quality gates](#quality-gates)
- [Release process](#release-process)
- [Rollback](#rollback)
- [Incident response](#incident-response)

## Components

| Component | Role | State |
|---|---|---|
| Frontend (Next.js) | UI and a same-origin proxy that forwards only the routes the UI uses | none |
| Backend (FastAPI), 1..N replicas | auth, rate limiting, generation, validation, execution | none when `CONVERSATION_STORE=postgres` and `RATE_LIMIT_BACKEND=redis`; otherwise per process |
| PostgreSQL | fleet data, `analytics` views, conversations, audit log | durable |
| Redis (optional) | shared rate-limit counters | disposable |
| LLM provider | SQL generation | external |
| Prometheus / Grafana / log store (yours) | metrics, dashboards, logs | external |

Per-process state is the reason the defaults differ from the multi-replica recommendation:
`memory` conversations and `memory` rate limiting are correct for **one** instance and wrong for
several (a restart or a different replica loses the conversation; each replica enforces its own
limit). Run several replicas only with `CONVERSATION_STORE=postgres` and `RATE_LIMIT_BACKEND=redis`.

## Fresh-environment walkthrough

This is the path a new engineer takes on an empty machine. It uses the mock provider, so no API key
is needed.

```bash
git clone <repository> && cd ai-sql-analytics-copilot
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD and ANALYTICS_DATABASE_PASSWORD to two different values

docker compose up -d --build              # postgres, migrate (one-shot), backend, frontend
docker compose --profile demo run --rm seed   # demo data; refuses when APP_ENV=production
open http://localhost:3000
```

Verify:

```bash
docker compose ps                                           # migrate: exited 0; others healthy
python scripts/smoke_test.py --base-url http://localhost:3000
make verify-permissions                                     # database privilege model
cd backend && python -m evals.run_eval --check-references   # dataset runs on this database
cd backend && python -m evals.run_eval --provider mock --subset mock
```

Optional stacks: `--profile redis` (shared rate limiter), `-f docker-compose.dev.yml` (backend on
`127.0.0.1:8000`), `-f docker-compose.loadtest.yml` (see [capacity.md](capacity.md)). For a real
model set `LLM_MODE=gemini` and `GEMINI_API_KEY` (or `GEMINI_API_KEY_FILE`).

For a production-shaped deployment use [`ops/kubernetes/analytics-backend.yaml`](../ops/kubernetes/analytics-backend.yaml)
as the starting point, with `APP_ENV=production`, `AUTH_MODE=jwt`, `CONVERSATION_STORE=postgres`,
`RATE_LIMIT_BACKEND=redis`, `AUDIT_SINK=both`, and every secret as a `*_FILE`.

## Health and probes

| Endpoint | Meaning | Use it for | Never fails because of |
|---|---|---|---|
| `GET /health` | the process is up | liveness probe | any dependency |
| `GET /health/ready` (also `/api/v1/health/ready`) | this instance can serve | readiness probe, load balancer, Compose healthcheck | an unconfigured LLM key, or Redis while failing open |
| `GET /api/v1/health/diagnostics` | dependency latency, pool state, migration revision, enabled features | operators (needs `METRICS_TOKEN`) | not a probe |

Readiness returns **503** when the application database, the analytics database, or (with
`RATE_LIMIT_FAIL_MODE=closed`) the rate limiter is unreachable. It returns **200** with
`{"status": "degraded", "degraded": [...]}` when something optional is unavailable: `llm_provider`
(no API key configured) or `rate_limiter` (Redis down while failing open). An orchestrator therefore
keeps a degraded instance in service rather than restarting it for something a restart cannot fix;
alerts, not probes, are how degradation is noticed. The Compose and Kubernetes examples encode this:
liveness never touches a dependency.

## Migrations

**Migrations run as a one-shot job, never at application start.** In Compose the `migrate` service
runs `alembic upgrade head` and the backend waits for it (`service_completed_successfully`); in
Kubernetes it is a `Job` applied before the rollout. This means scaling the backend to ten replicas
runs one migration, not ten racing ones, and a failed migration stops the deploy before any new code
serves traffic.

### Expand and contract

Because replicas are replaced gradually, **the old and the new application version run against the
same database for a while.** Every migration must therefore be compatible with both:

1. **Expand** (release N): add tables, columns (nullable or with a default), indexes, and views. Do
   not remove or rename anything the previous version reads or writes. Deploy code that works with
   both shapes. `c3d91e5a7b20` (conversations, audit) is an example: three new tables, nothing
   altered.
2. **Migrate data** if needed, in batches, outside the schema migration.
3. **Contract** (release N+1 or later, after N is fully rolled out and rollback to N-1 is no longer
   needed): drop the old column or table, add `NOT NULL`, tighten constraints.

Rules of thumb: add `CREATE INDEX CONCURRENTLY` outside a transaction for large tables; never
combine a rename with a deploy (add the new name, copy, switch reads, switch writes, then drop);
write `downgrade()` for every migration and test it on a copy.

The `analytics` views (`b7c2d41f8a10`) are part of the security boundary: after any migration that
touches a fleet table, run `make verify-permissions` and `pytest -m integration`.

### Upgrading a cluster

```bash
docker compose run --rm migrate          # or the Kubernetes Job
docker compose exec postgres psql -U app -d app -c "SELECT version_num FROM alembic_version"
make verify-permissions
```

## Scaling

Capacity is bounded by connection pools, not CPU: an `/ask` holds an **analytics** connection only
while its SQL runs (milliseconds to seconds), not while the LLM thinks (seconds). Measure with
[capacity.md](capacity.md) and size from the result.

- **Replicas:** add backend replicas for more concurrent LLM calls. Use
  `CONVERSATION_STORE=postgres` and `RATE_LIMIT_BACKEND=redis` first.
- **Pools:** per replica, the analytics engine may hold `DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW`
  (default 15) connections and the application engine the same. Keep
  `replicas x 2 x (pool + overflow)` below PostgreSQL's `max_connections` minus headroom for
  migrations and administrators; use PgBouncer in transaction mode if you need more.
  (The executor sets transaction-local settings only, so transaction pooling is safe.)
- **Concurrency:** each in-flight `/ask` occupies a threadpool worker (default 40 in Starlette) and a
  provider thread (16). Raise uvicorn workers or replicas before raising those limits.
- **Redis:** one small instance is enough; keys are one sorted set per principal and route family,
  each expiring with the window.
- **Query cost:** `QUERY_COST_LIMIT` (planner cost units, default 1,000,000) rejects runaway plans
  before they run. Re-derive it from `EXPLAIN` costs of your heaviest legitimate queries when the
  data volume changes.

## Secrets and rotation

Provide secrets as files (`DATABASE_URL_FILE`, `ANALYTICS_DATABASE_URL_FILE`, `GEMINI_API_KEY_FILE`,
`JWT_SECRET_FILE`, `JWT_PUBLIC_KEY_FILE`, `METRICS_TOKEN_FILE`, `REDIS_URL_FILE`, ...): Docker/Compose
`secrets:`, Kubernetes `Secret` volumes, or a secret-manager agent that renders files. A file keeps
the value out of `docker inspect`, `kubectl describe`, and the process environment. Setting both
`NAME` and `NAME_FILE` is a startup error, so a rotated file can never be shadowed by a stale
variable.

Startup validates the whole configuration and exits with every problem named and no values, for
example:

```
Invalid configuration:
  - AUTH_MODE: Production requires AUTH_MODE=jwt.
  - GEMINI_API_KEY_FILE: the file is missing or unreadable
```

Rotation steps for each secret, and the order that avoids downtime, are in
[runbooks/credential-rotation.md](runbooks/credential-rotation.md). Rotate on a schedule (at least
yearly for database passwords, quarterly for API keys), on departures, and immediately after any
suspected exposure.

## Observability

- **Metrics:** `GET /api/v1/metrics/prometheus` (Prometheus text) and `GET /api/v1/metrics` (JSON),
  both requiring `Authorization: Bearer $METRICS_TOKEN`, neither proxied by the frontend. Scrape
  every replica directly (`ops/prometheus/prometheus.yml`). Labels are bounded: route templates,
  methods, status codes, provider names, fixed error codes. Question text, SQL, principals, and
  request ids are never labels.
- **Dashboards and alerts:** `ops/grafana/dashboard.json`, `ops/prometheus/alerts.yml`,
  `ops/prometheus/slo-rules.yml`; objectives in [slos.md](slos.md).
- **Tracing (optional):** `OTEL_ENABLED=true` plus `OTEL_EXPORTER_OTLP_ENDPOINT`; install with
  `pip install ".[tracing]"`. Spans: `http.request` -> `llm.call`, `sql.validate`, `sql.execute`,
  carrying the request id, provider, row count, and status. Never question text or SQL.
- **Logs:** structured JSON with request id, conversation id, endpoint, durations, repair count,
  status; no questions, SQL, tokens, or URLs.
- **Audit trail** (`AUDIT_SINK=log|database|both`): one event per `/ask` and per feedback with
  principal, customer, conversation id, request id, a SHA-256 of the SQL, tables, row count,
  duration, and outcome. It holds no content, so it can be retained and reviewed without becoming a
  second copy of the data. Use `sql_hash` to find repeats and `request_id` to join with logs.
- **Request correlation:** the answer carries `request_id`; errors show "Reference: ..."; feedback
  and audit events use the same id.

## Backup and restore

What needs backing up: the PostgreSQL database (fleet data, conversations, audit log). Redis, the
metrics, and the containers are disposable. Secrets live in your secret store.

```bash
scripts/backup_postgres.sh                 # compressed pg_dump -Fc archive, verified with pg_restore --list
scripts/restore_drill.sh                   # back up, restore into a scratch database, compare counts
scripts/restore_postgres.sh <dump> <db>    # restore (defaults to the scratch database)
```

- Schedule `backup_postgres.sh` at least daily (and use your platform's point-in-time recovery if
  it has one); keep archives encrypted, access-restricted, and for the same retention as the
  database.
- **Restoring over the live `app` database** requires stopping the backend first and
  `CONFIRM_RESTORE_LIVE=yes`; the scripts refuse otherwise.
- The `analytics_readonly` role is not part of a database dump. After restoring into a fresh cluster
  run `database/init/01-analytics-role.sql`, `alembic upgrade head`, and `make verify-permissions`.
- **Drill it.** A backup you have not restored is a hope, not a backup. Run `restore_drill.sh`
  quarterly and after changing the database version or schema approach; record the result using
  [drills/README.md](drills/README.md). Exit code 1 means backups cannot be trusted: treat that as an
  incident.

## Retention

```bash
python -m app.jobs.purge        # {"conversations_purged": N, "audit_records_purged": M}
```

Run it daily (the Kubernetes CronJob and `docker compose --profile ops run --rm purge` do). It
deletes conversations idle longer than `CONVERSATION_TTL_DAYS` (default 30) and audit rows older than
`AUDIT_RETENTION_DAYS` (default 365). Users can delete their own conversations from the UI
(`DELETE /api/v1/analytics/conversations/{id}`). The demo seed never runs in production.

## Quality gates

CI (`.github/workflows/ci.yml`) blocks merges on:

| Gate | Checks |
|---|---|
| Backend lint and format | `ruff check`, `ruff format --check` |
| Types | `mypy app` (lenient baseline; tighten module by module) |
| Unit tests with coverage | `pytest` excluding integration/fuzz; per-package coverage minimums via `scripts/check_coverage.py` |
| Integration | PostgreSQL service container: init script, migrations, seed, `pytest -m integration` with `REQUIRE_INTEGRATION=1` so a missing database **fails** instead of skipping |
| Fuzz | validator fuzz with a fixed seed on every push; much longer run nightly |
| Evaluation | `evals.run_eval --provider mock --subset mock` plus `--check-references` against seeded PostgreSQL |
| Frontend | `eslint`, `vitest`, `next build`, contract test against the backend |
| End to end | Playwright + axe against the Compose stack in mock mode |
| Supply chain | `pip-audit`, `npm audit --omit=dev --audit-level=high`, Docker image builds, Trivy image scan (high and critical fail) |
| Compose | `docker compose config` for the base and override files |

Scheduled workflows: nightly full evaluation against the real provider
(`.github/workflows/nightly.yml`, needs `GEMINI_API_KEY`), a longer fuzz run, and the load test
(`.github/workflows/loadtest.yml`).

Coverage minimums (`scripts/check_coverage.py`): `app/analytics` 85 %, `app/services` 80 %,
`app/llm` 75 %. They were set before the first measured baseline; **raise them to just under the
measured values and never lower them to pass a build.**

The backend lockfile is generated, not hand-edited: `make lock` writes `backend/requirements.lock`
(hash-pinned, from `pyproject.toml`) and CI verifies it is current once it exists. Dependabot opens
weekly update PRs for pip, npm (frontend and e2e), Docker, and GitHub Actions.

## Release process

Releases are tag-driven (`.github/workflows/release.yml`):

1. Merge to `main` with CI green. Tag with semantic versioning: `git tag v1.2.0 && git push --tags`.
2. The workflow runs the test suites, builds both images, scans them (Trivy), pushes them to the
   registry as `ghcr.io/<owner>/analytics-backend:1.2.0` and `...-frontend:1.2.0` (immutable
   version tags plus the commit digest), attaches an SBOM to each image, and publishes release notes
   generated from conventional commits (`scripts/release_notes.py`).
3. **Staging:** the workflow deploys the tagged images, runs the migration job, and runs
   `scripts/smoke_test.py` (liveness, readiness, and one authenticated `/ask`).
4. **Production:** a protected environment (manual approval) deploys the same images; the migration
   job runs first; the smoke test runs again. A failed smoke test marks the release failed and does
   not leave a half-promoted state: the previous version keeps serving until the new pods are ready
   (`maxUnavailable: 0`).
5. After promotion, watch the dashboard for 30 minutes: availability, latency, answer rate.

Deployment targets are not configured in the repository because they depend on your platform; the
workflow's deploy steps call `scripts/deploy.sh <environment> <version>` hooks you provide, so the
pipeline's gating, smoke testing, and notes work unchanged on Kubernetes, Compose hosts, or a PaaS.

## Rollback

Rolling back means deploying the previous immutable tag. Because migrations are expand-only until
the old version is retired, the previous version still works against the migrated database.

1. Identify the last good tag (`git tag --sort=-creatordate | head`).
2. Redeploy it (`scripts/deploy.sh production v1.1.0`, or `kubectl set image ...`). Do **not** run
   `alembic downgrade` unless the new release included a contracting migration and you have a
   database backup; downgrades can destroy data.
3. Run `python scripts/smoke_test.py --base-url <url> --token <token>`.
4. Open an incident review: what failed, why CI did not catch it, which test now will.

**Rehearse the rollback** at least once per quarter in staging (deploy N, then N-1, smoke test) and
record it with the restore drills. A rollback that has never been run is untested.

## Incident response

1. **Acknowledge** the page; open the dashboard (`ops/grafana/dashboard.json`) and check, in order:
   availability, LLM errors, SQL errors, rate-limit rejections, deadline exceeded.
2. **Classify** with the alert's runbook:
   [LLM provider](runbooks/llm-provider-outage.md),
   [database](runbooks/database-saturation.md),
   [rate limiting](runbooks/rate-limit-storm.md),
   [suspected data leak](runbooks/suspected-data-leak.md),
   [credentials](runbooks/credential-rotation.md).
3. **Backend instance down** (`AnalyticsBackendDown`): `GET /health` on the instance; if it answers,
   the scrape token or network is the problem; if not, check the container logs for
   `Invalid configuration:` (a bad secret or setting) and the orchestrator's last event.
4. **Contain before debugging** whenever data exposure is possible.
5. **Communicate** early: a one-line status beats silence. Include the `request_id` users see.
6. **Review** within a week: timeline, root cause, detection, what changes (a test, an alert, a
   runbook step). Link the review from the runbook that was used.
