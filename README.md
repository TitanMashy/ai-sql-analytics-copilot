# AI SQL Analytics Copilot

The AI SQL Analytics Copilot turns natural-language fleet questions into safe, explainable SQL workflows. Its Next.js dashboard presents backend-validated results as conversations, KPIs, charts, tables, and generated SQL.

## Architecture

The system is a modular monolith: Next.js presentation layer -> FastAPI -> schema/business context -> Gemini or mock provider -> SQLGlot validation -> PostgreSQL read-only execution -> result intelligence. SQL generation, validation, metric definitions, summaries, and visualization selection remain backend-owned.

End-to-end, a request is authenticated (signed bearer token) and rate limited per principal; a question is length-validated and assigned a request ID; schema and business definitions are retrieved; the selected provider returns structured SQL; `/generate` returns that SQL without execution, while `/ask` sends it through AST validation, bounded repair when a classified error is repairable, and the read-only query service. Successful rows then receive KPI, visualization, warning, and grounded summary metadata for the frontend. No provider-generated SQL bypasses validation.

See [docs/architecture.md](docs/architecture.md), [docs/database-schema.md](docs/database-schema.md), [docs/business-definitions.md](docs/business-definitions.md), [docs/deployment.md](docs/deployment.md), and [docs/production-security-review.md](docs/production-security-review.md).

## Stack

- Python 3.12+, FastAPI, Pydantic, SQLAlchemy, psycopg, SQLGlot, Alembic
- PostgreSQL 16, Gemini SDK, deterministic mock provider
- Next.js 16, React 19, TypeScript, Tailwind CSS, Recharts, Vitest
- Docker Compose, pytest, Ruff, GitHub Actions

## Local Development

Backend virtual environment and dependencies:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Without `.env`, the backend uses local SQLite defaults and `AUTH_MODE=disabled` (a development-only mode that production rejects). Start it with `make dev`; the API is at http://localhost:8000. `GET /health` is liveness, `GET /health/ready` checks required databases/provider configuration, and development API docs are at `/docs`.

To use a configured PostgreSQL database, run `make migrate` and `make seed`. Seeding is deterministic and idempotent.

Run the frontend separately:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. Next.js proxies only the routes the dashboard uses (`ask`, conversations, schema tables, health) to `http://localhost:8000`, keeping browser calls same-origin; direct-SQL, SQL-validation, SQL-generation, and metrics routes are not reachable through it. `INTERNAL_API_URL` is applied when `next build` evaluates the proxy rewrites. The browser receives no provider or database credentials. With `AUTH_MODE=jwt` the dashboard asks for an access token (`python backend/scripts/issue_token.py --customer-id 7` issues one for local testing).

## APIs and Security

- `POST /api/v1/analytics/generate` generates SQL without executing it.
- `POST /api/v1/analytics/ask` generates, validates, executes, and returns result intelligence.
- `POST /api/v1/analytics/query` and `/validate` expose the internal direct-SQL surface. They are not mounted in production unless `ENABLE_DIRECT_SQL_ENDPOINTS=true`.
- `GET /api/v1/metrics` returns process-local counters and latency averages; it needs `METRICS_TOKEN` when set and is disabled in production when unset.
- Every analytics and schema route needs `Authorization: Bearer <token>` (outside `AUTH_MODE=disabled`); health endpoints are open.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe. |
| GET | `/health/ready` | Readiness check for application DB, analytics DB, and provider configuration. |
| GET | `/api/v1/health` | Compatibility application-database health check. |
| GET | `/api/v1/health/ready` | Versioned readiness alias. |
| GET | `/api/v1/metrics` | Process-local counters and average latencies. Bearer `METRICS_TOKEN`; disabled in production when unset. |
| POST | `/api/v1/analytics/generate` | Generate structured SQL without execution. |
| POST | `/api/v1/analytics/ask` | Generate, validate, execute, and analyze results. Accepts optional `conversation_id` and bounded `conversation_context`. |
| POST | `/api/v1/analytics/query` | Validate and execute one direct read-only SQL statement (gated; see above). |
| POST | `/api/v1/analytics/validate` | Validate SQL without executing it (gated; see above). |
| POST | `/api/v1/analytics/conversations` | Create an in-memory conversation. |
| GET | `/api/v1/analytics/conversations/{conversation_id}` | Inspect an in-memory conversation. |
| POST | `/api/v1/analytics/conversations/{conversation_id}/turns` | Append a bounded user turn to your own conversation. |
| GET | `/api/v1/schema`, `/api/v1/schema/tables`, `/api/v1/schema/tables/{table_name}` | Read schema metadata. |
| GET | `/docs` | Interactive API documentation outside production mode. |

Errors use `{ "error": { "code": "...", "message": "...", "request_id": "..." } }` (outside production, `QUERY_GENERATION_FAILED` also carries `error.debug.sql`). Requests are size- and length-limited; every analytics, conversation, and schema route has configurable per-principal rate limits, with a stricter limit on LLM-backed calls, and each question has an overall time budget (`REQUEST_DEADLINE_SECONDS`). PostgreSQL statement timeout, an enforced outer `LIMIT` (results over `MAX_RESULT_ROWS` are truncated and flagged), table/column/function allowlists, and AST validation remain enforced for generated and repaired SQL. Generated SQL is always untrusted.

The analytics DB uses a separate `analytics_readonly` role with a distinct password. It has no privileges on the application tables; it reads PII-free, tenant-scoped views in the `analytics` schema inside read-only transactions, and each query is limited to the authenticated principal's customer (`analytics_admin` sees all). Do not grant it writes or use application-owner credentials for analytics execution. See [docs/security.md](docs/security.md) for SQL controls and [docs/production-security-review.md](docs/production-security-review.md) for implemented controls versus recommended future controls. AST validation is defense in depth, not a complete security guarantee.

Set `LLM_MODE=gemini`, `GEMINI_API_KEY`, and `GEMINI_MODEL` for Gemini. Mock mode requires no key and is disabled in production. Provider failures are bounded and classified; generated SQL is never executed after provider failure.

Representative supported questions in deterministic mock mode include:

- How many active vehicles do we have?
- What were the top 10 customers by revenue?
- Show monthly revenue for the last 12 months.
- Which vehicles had the highest idle time?
- Show fuel consumption by vehicle.

For follow-ups, send `conversation_id` on subsequent `/ask` calls. The backend retains at most eight recent turns and 2,000 context characters by default. Conversation state is process-local and is not durable or user-authenticated; caller context is untrusted prompt data, not an authorization input.

The repair loop is deliberately narrow: only classified repairable parse/schema/execution errors are sent back to the provider, with a configurable maximum of three attempts. Every repaired query returns through the same SQLGlot validator and read-only executor. Security, permission, timeout, complexity, and result-limit failures are not automatically repaired.

## Docker Compose

Copy `.env.example` to `.env`, replace both owner and read-only password placeholders with distinct credentials, and keep `.env` out of Git. Initialize and seed the database before starting the application:

```bash
docker compose up -d postgres
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m app.db.seed
docker compose up --build -d
```

Dashboard: http://localhost:3000. The backend is not published to the host; use `docker compose -f docker-compose.yml -f docker-compose.dev.yml up` to expose it on `127.0.0.1:8000` for debugging. Compose waits for PostgreSQL and backend readiness. The backend container is non-root with a read-only root filesystem, and both application images have health checks. Stop with `docker compose down`; do not add `--volumes` unless deleting database state is intended.

The PostgreSQL init script sets the `analytics_readonly` password only for new clusters. Changing environment variables does not rotate credentials in an already-initialized database; rotate both roles explicitly and update both connection URLs.

## Configuration and Operations

`APP_ENV=production` disables debug/docs and rejects SQLite URLs and mock LLM mode. Configure exact `CORS_ALLOWED_ORIGINS` only when direct cross-origin browser access is required; the Next proxy is same-origin by default. Pool sizes, connection/query/provider timeouts, request limits, rate limits, repair attempts, and result caps are environment-configurable. Do not put real secrets in image build args, source control, or logs.

Configuration lives in `.env.example` and the full setting-by-setting reference is in [docs/deployment.md](docs/deployment.md). Important values include `DATABASE_URL`, `ANALYTICS_DATABASE_URL`, distinct `POSTGRES_PASSWORD` and `ANALYTICS_DATABASE_PASSWORD`, `APP_ENV`, `LLM_MODE`, `GEMINI_API_KEY`, `CORS_ALLOWED_ORIGINS`, `MAX_REQUEST_BODY_BYTES`, `MAX_QUESTION_LENGTH`, `MAX_CONVERSATION_CONTEXT_CHARS`, `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`, pool settings, `QUERY_TIMEOUT_SECONDS`, `MAX_RESULT_ROWS`, and `MAX_REPAIR_RETRIES`.

`GET /health` is liveness; `GET /health/ready` checks application and analytics DBs plus provider configuration. JSON logs carry request/conversation IDs and LLM, validation, SQL, repair, row-count, total-duration, and response-status metadata without logging questions, SQL, API keys, or full URLs. Restrict `/api/v1/metrics` to a trusted network.

## Testing and CI

Backend:

```bash
make test
make lint
```

Frontend:

```bash
cd frontend
npm ci
npm test -- --run
npm run lint
npm run build
```

The backend smoke test exercises active vehicles, total revenue, top customers, monthly revenue, idle time, and fuel queries; it records SQL and total API latency. GitHub Actions runs backend install/lint/tests, frontend install/lint/tests/build, and Compose configuration validation using mock mode without a Gemini key.

## Portfolio Notes

- **What I built:** an end-to-end conversational analytics MVP for fleet operations, from natural-language questions through validated SQL to a responsive results dashboard.
- **Why:** make operational and revenue questions accessible while keeping generated SQL explainable and constrained by an independent security boundary.
- **Engineering challenges:** maintaining a strict SQL trust boundary across generation, repair, and execution; bounding conversation and request size; and making provider/database failures observable without leaking sensitive input.
- **Technical decisions:** modular monolith rather than extra services; provider abstraction with deterministic mock mode; SQLGlot AST validation plus a separate PostgreSQL read-only role; backend-selected visualization metadata; and process-local metrics/rate limiting sized to the current Compose deployment.
- **Security considerations:** model output is untrusted; all generated and repaired SQL is revalidated; database URLs/keys are runtime secrets; request bodies and expensive endpoints are bounded; and errors/logging use request IDs without returning stack traces or recording questions/SQL.
- **Production-oriented work:** environment-specific settings, pooled connections and timeouts, health/readiness, structured telemetry, bounded Gemini retries, non-root containers, distinct DB credentials, and automated CI checks. These controls do not replace authentication, tenant isolation, shared multi-instance services, or a managed production ingress.

## Limitations

The service validates signed tokens and scopes data per customer, but it has no identity provider (supply tokens with `sub`, `iss`, `aud`, `exp`, `roles`, `customer_id`), no durable conversation storage, no shared multi-instance rate limiter, and no external metrics aggregation. Rate limits, metrics, and conversations are process-local. This is a production-oriented MVP, not an enterprise security certification. See [docs/deployment.md](docs/deployment.md) for deployment steps and operational caveats.

Future improvements include an identity provider integration, durable conversation history, shared rate limiting and metrics, query-cost controls, and deployment-specific TLS/ingress policy. These are not implemented.
