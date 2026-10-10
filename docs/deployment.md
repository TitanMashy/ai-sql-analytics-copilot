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
| `LLM_PROVIDER` | `mock`, `gemini` or `ollama` | `mock` needs no provider key; no fallback between providers. `LLM_MODE` is no longer accepted. |
| `GEMINI_API_KEY` | Gemini credential | Supply through the runtime environment or a secret manager; never bake it into an image. |
| `LLM_MODEL` | Model ID | Gemini default `gemini-3.6-flash`; required for Ollama. Providers retire model ids, so set it explicitly. `GEMINI_MODEL` is no longer accepted. |
| `OLLAMA_BASE_URL`, `LLM_MAX_RETRIES` | Ollama address; extra attempts after a transient failure | `http://localhost:11434` (Compose: `host.docker.internal`); `1`. |
| `LLM_TIMEOUT_SECONDS` | Provider request timeout | Retries are applied once, in the application, only for transient provider failures. See [llm-providers.md](llm-providers.md). |
| `CORS_ALLOWED_ORIGINS` | JSON array of browser origins | Empty by default. The same-origin Next.js proxy normally makes CORS unnecessary. |
| `MAX_QUESTION_LENGTH` | Natural-language question characters | Defaults to 2,000. |
| `MAX_CONVERSATION_CONTEXT_CHARS` | Caller-supplied context/turn characters | Defaults to 2,000. |
| `MAX_REQUEST_BODY_BYTES` | Maximum buffered HTTP body | Defaults to 16 KiB, with a hard setting ceiling of 1 MiB. |
| `RATE_LIMIT_ENABLED` | Enable process-local throttling | Keep enabled. |
| `RATE_LIMIT_REQUESTS` | Requests per route family and principal per window | Defaults to 30. |
| `RATE_LIMIT_LLM_REQUESTS` | Stricter limit for `/generate` and `/ask` | Defaults to `min(RATE_LIMIT_REQUESTS, 20)`. |
| `RATE_LIMIT_WINDOW_SECONDS` | Sliding window size | Defaults to 60 seconds. |
| `REQUEST_DEADLINE_SECONDS` | Overall budget for one `/ask` | Defaults to 25. Keep it below the frontend's 30-second timeout. |
| `AUTH_MODE` | `jwt`, `static` (development), or `disabled` (development) | Production requires `jwt`. |
| `JWT_ALGORITHM` | `HS256`, `RS256`, or `ES256` | `RS256` by default. |
| `JWT_SECRET` | HS256 signing secret | 32+ characters; supply through a secret store. |
| `JWT_PUBLIC_KEY` | PEM public key for RS256/ES256 | Supply through a secret store. |
| `JWT_ISSUER`, `JWT_AUDIENCE` | Required token claims | Both are required in `jwt` mode. |
| `ENABLE_DIRECT_SQL_ENDPOINTS` | Mount `/analytics/query` and `/validate` | Off by default in production. |
| `METRICS_TOKEN` | Bearer token for `/api/v1/metrics` | Unset in production disables the endpoint. |
| `FORWARDED_ALLOW_IPS` | Trusted proxy addresses for `X-Forwarded-For` (uvicorn) | Compose sets `*` because only the frontend reaches the backend; otherwise name the proxy. |
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

Production configuration rejects SQLite URLs and the deterministic mock provider. Use PostgreSQL and a configured real provider (Gemini or Ollama); mock mode remains available in development and test environments.

## Docker Compose

For local development, use the mock provider and run migrations/seeding before starting the complete stack:

```bash
LLM_MODE=mock docker compose up -d postgres

docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m app.db.seed

docker compose up --build -d
```

The dashboard is at http://localhost:3000. The backend publishes no host port: the Next.js server proxies only the routes the UI needs (`ask`, conversations, schema tables, health) to the backend service, so `/query`, `/validate`, `/generate`, and `/metrics` are unreachable from the browser. To call the backend directly while developing, add the override file, which publishes `127.0.0.1:8000` and enables the direct-SQL endpoints:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Stop the stack with `docker compose down`; this does not request volume deletion. The default `AUTH_MODE=disabled` is for local use only. To exercise authentication locally, set `AUTH_MODE=jwt`, `JWT_ALGORITHM=HS256`, `JWT_SECRET`, `JWT_ISSUER`, and `JWT_AUDIENCE`, then paste the output of `python backend/scripts/issue_token.py --customer-id 7` (or `--admin`) into the dashboard's sign-in prompt.

For Gemini, set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` in the runtime environment before starting the backend. CI and credential-free demos use the deterministic mock provider.

The backend container runs as a non-root user, installs runtime dependencies only, has a read-only root filesystem with a temporary `/tmp`, drops Linux capabilities, and has a readiness health check. The frontend uses the standalone Next.js output and a non-root runtime. PostgreSQL initialization creates the read-only role with a distinct password (`ANALYTICS_DATABASE_PASSWORD`) for new clusters and grants it no table privileges; the `b7c2d41f8a10` migration creates the `analytics` views and grants the role `SELECT` on those only.

## Database Changes

Migrations are explicit; the API does not run Alembic at startup:

```bash
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m app.db.seed
```

Seeding is deterministic and idempotent. The application role owns migrations; analytics requests use only `ANALYTICS_DATABASE_URL`. Keep PostgreSQL network access private. Run migrations before starting a new backend version: until the `analytics` views exist the read-only role can read nothing, so analytics queries fail closed.

Upgrading an existing cluster: run `alembic upgrade head` as the application owner. The migration creates the views, then (if the role exists) grants the views, revokes all privileges and default privileges on `public`, and sets the role's `search_path` to `analytics`. Run `make verify-permissions` afterwards. `alembic downgrade` restores the previous grants.

## Health, Metrics, and Logs

- `GET /health` is liveness and does not contact dependencies.
- `GET /health/ready` checks the application database, analytics database, and required provider configuration. It returns 503 when a required dependency is unavailable.
- `GET /api/v1/health` remains as a compatibility check for the application database.
- `GET /api/v1/health/ready` is the versioned readiness alias.
- `GET /api/v1/metrics` returns process-local counters and average latencies as JSON. It requires `Authorization: Bearer $METRICS_TOKEN` when the token is set and is disabled in production when it is not. It is never proxied by the frontend; scrape it from inside the network.

Request logs include request/conversation IDs, endpoint, total duration, LLM/validation/SQL durations, result row count where applicable, repair count, and status. Questions, SQL text, API keys, and connection URLs are not logged by application instrumentation. Keep access to logs and the metrics endpoint controlled at the network gateway.

## Security Boundaries

The LLM output remains untrusted. SQLGlot validation, the table/column rules, query complexity limits, PostgreSQL statement timeout, row limit, and read-only database role remain mandatory. Do not grant writes to `analytics_readonly` or expose it to application-owner credentials. CORS is opt-in and should list exact origins when needed. The frontend receives no provider or database secrets.

Use HTTPS at a trusted reverse proxy and restrict public access to the API, metrics, database, and logs. Configure `CORS_ALLOWED_ORIGINS` only for the browser origins that must call the backend directly. Prefer the existing same-origin Next proxy where possible.

## Limitations

Rate limiting, metrics, and conversations are process-local. Multi-instance deployments need a shared rate limiter, metrics aggregation, and durable conversation storage. The application validates signed tokens and scopes every query to the token's customer, but it does not issue tokens: supply an identity provider (or your own issuer) that sets `sub`, `iss`, `aud`, `exp`, `roles`, and `customer_id`. Result caching is intentionally absent because invalidation policy is not defined. `INTERNAL_API_URL` is applied when `next build` evaluates the proxy rewrites, so it is a build-time value for the frontend image. Production connection-pool sizing should follow real load tests and the PostgreSQL connection budget.


## Sprint 12 settings and services

| Variable | Purpose | Default |
|---|---|---|
| `CONVERSATION_STORE` | `memory` or `postgres` (durable, shared by replicas; needs migrations) | `memory`; Compose uses `postgres` |
| `CONVERSATION_TTL_DAYS`, `CONVERSATION_MAX_PER_OWNER`, `CONVERSATION_MAX_TURNS` | retention and caps | 30, 200, 8 |
| `QUERY_COST_LIMIT` | reject plans above this PostgreSQL cost; empty disables | 1,000,000 |
| `AUDIT_SINK`, `AUDIT_RETENTION_DAYS` | `log`, `database`, or `both` | `log`; Compose `both`; 365 |
| `<SECRET>_FILE` | read `DATABASE_URL`, `ANALYTICS_DATABASE_URL`, `GEMINI_API_KEY`, `JWT_SECRET`, `JWT_PUBLIC_KEY`, or `METRICS_TOKEN` from a file | setting both is a startup error |

Compose adds a one-shot `migrate` service (the backend waits for it), plus `seed` (profile `demo`) and `purge` (profile `ops`). Readiness (`/health/ready`) returns 503 only for required dependencies and 200 with `{"status": "degraded"}` for optional ones. Operating, releasing, rolling back, and incident response: [operations.md](operations.md).
