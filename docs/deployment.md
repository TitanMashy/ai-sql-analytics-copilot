# Deployment Guide

This repository is a single FastAPI service, a Next.js application, and PostgreSQL in Docker Compose. It is a production-oriented MVP, not a complete multi-tenant hosted service. No cloud resources or extra services are required.

## Configuration

Copy `.env.example` to `.env` for local Compose use. `.env` is ignored by Git. Replace every sample credential before exposing the stack outside a developer machine.

| Variable | Purpose | Guidance |
|---|---|---|
| `APP_ENV` | `development`, `test`, or `production` | Use `production` for deployment. |
| `DEBUG` | Framework debug behavior | Keep `false` in production; production settings force effective debug off. |
| `DATABASE_URL` | Migration/application-owner database | Use a PostgreSQL URL with percent-encoded credentials. |
| `ANALYTICS_DATABASE_URL` | Restricted query connection | Use the separate `analytics_readonly` role. |
| `POSTGRES_PASSWORD` | Fresh Compose database bootstrap | Use a unique secret; replace the `.env.example` placeholder. |
| `ANALYTICS_DATABASE_PASSWORD` | Fresh `analytics_readonly` role bootstrap | Use a different secret from `POSTGRES_PASSWORD`. |
| `LLM_MODE` | `mock`, `gemini`, or legacy `openai` | `mock` needs no provider key. |
| `GEMINI_API_KEY` | Gemini credential | Supply through the runtime environment or a secret manager; never bake it into an image. |
| `GEMINI_MODEL` | Gemini model ID | Select a model available to the configured account. |
| `LLM_TIMEOUT_SECONDS` | Provider request timeout | SDK retries are bounded to transient 5xx responses. |
| `CORS_ALLOWED_ORIGINS` | JSON array of browser origins | Empty by default. The same-origin Next.js proxy normally makes CORS unnecessary. |
| `MAX_QUESTION_LENGTH` | Natural-language question characters | Defaults to 2,000. |
| `MAX_CONVERSATION_CONTEXT_CHARS` | Caller-supplied context/turn characters | Defaults to 2,000. |
| `MAX_REQUEST_BODY_BYTES` | Maximum buffered HTTP body | Defaults to 16 KiB, with a hard setting ceiling of 1 MiB. |
| `RATE_LIMIT_ENABLED` | Enable process-local throttling | Keep enabled. |
| `RATE_LIMIT_REQUESTS` | Requests per endpoint/client window | Defaults to 30. |
| `RATE_LIMIT_WINDOW_SECONDS` | Sliding window size | Defaults to 60 seconds. |
| `DATABASE_POOL_SIZE` | Per-process pool size for each engine | Defaults to 5. |
| `DATABASE_MAX_OVERFLOW` | Temporary connections beyond pool size | Defaults to 10. |
| `DATABASE_POOL_TIMEOUT_SECONDS` | Pool checkout timeout | Defaults to 5 seconds. |
| `DATABASE_POOL_RECYCLE_SECONDS` | Connection recycling interval | Defaults to 1,800 seconds. |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | PostgreSQL connection timeout | Defaults to 5 seconds. |
| `QUERY_TIMEOUT_SECONDS` | PostgreSQL statement timeout | Defaults to 10 seconds. |
| `MAX_RESULT_ROWS` | Maximum analytics result rows | Defaults to 1,000. |
| `MAX_REPAIR_RETRIES` | Maximum repair attempts | Defaults to 3; security and timeout failures are not repaired. |
| `LOG_LEVEL` | Application log level | Defaults to `INFO`; logs are structured JSON. |

The Compose URLs use distinct owner and read-only credentials on a fresh local database. Percent-encode reserved URL characters if using a password in a SQLAlchemy URL. For an existing initialized database, changing either password does not change PostgreSQL roles: rotate the `app` and `analytics_readonly` role passwords explicitly and update both URLs before enabling password authentication.

Production configuration rejects SQLite URLs and the deterministic mock provider. Use PostgreSQL and a configured Gemini or OpenAI provider; mock mode remains available in development and test environments.

## Docker Compose

For local development, use the mock provider and run migrations/seeding before starting the complete stack:

```bash
LLM_MODE=mock docker compose up -d postgres

docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m app.db.seed

docker compose up --build -d
```

The dashboard is at http://localhost:3000 and the API is at http://localhost:8000. The Next.js server proxies `/api/*` to the backend service. Stop the stack with `docker compose down`; this does not request volume deletion.

For Gemini, set `LLM_MODE=gemini` and `GEMINI_API_KEY` in the runtime environment before starting the backend. CI and credential-free demos use the deterministic mock provider.

The backend container runs as a non-root user, installs runtime dependencies only, has a read-only root filesystem with a temporary `/tmp`, drops Linux capabilities, and has a readiness health check. The frontend uses the standalone Next.js output and a non-root runtime. PostgreSQL initialization creates the read-only role and grants SELECT; its distinct password is taken from `ANALYTICS_DATABASE_PASSWORD` for new clusters.

## Database Changes

Migrations are explicit; the API does not run Alembic at startup:

```bash
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m app.db.seed
```

Seeding is deterministic and idempotent. The application role owns migrations; analytics requests use only `ANALYTICS_DATABASE_URL`. Keep PostgreSQL network access private. Compose publishes the backend port for local use; remove that host mapping or restrict it behind a trusted TLS-terminating gateway for deployment.

## Health, Metrics, and Logs

- `GET /health` is liveness and does not contact dependencies.
- `GET /health/ready` checks the application database, analytics database, and required provider configuration. It returns 503 when a required dependency is unavailable.
- `GET /api/v1/health` remains as a compatibility check for the application database.
- `GET /api/v1/health/ready` is the versioned readiness alias.
- `GET /api/v1/metrics` returns process-local counters and average latencies as JSON.

Request logs include request/conversation IDs, endpoint, total duration, LLM/validation/SQL durations, result row count where applicable, repair count, and status. Questions, SQL text, API keys, and connection URLs are not logged by application instrumentation. Keep access to logs and the metrics endpoint controlled at the network gateway.

## Security Boundaries

The LLM output remains untrusted. SQLGlot validation, the table/column rules, query complexity limits, PostgreSQL statement timeout, row limit, and read-only database role remain mandatory. Do not grant writes to `analytics_readonly` or expose it to application-owner credentials. CORS is opt-in and should list exact origins when needed. The frontend receives no provider or database secrets.

Use HTTPS at a trusted reverse proxy and restrict public access to the API, metrics, database, and logs. Configure `CORS_ALLOWED_ORIGINS` only for the browser origins that must call the backend directly. Prefer the existing same-origin Next proxy where possible.

## Limitations

Rate limiting, metrics, and conversations are process-local. Multi-instance deployments need a shared rate limiter, metrics aggregation, and durable conversation storage. The application has no user authentication, tenant authorization, or per-tenant query policy; do not expose customer data as a public multi-tenant service without those controls. The metrics endpoint is not authenticated and should be restricted by the deployment network. Result caching is intentionally absent because authorization scope and invalidation policy are not defined. Production connection-pool sizing should follow real load tests and the PostgreSQL connection budget.
