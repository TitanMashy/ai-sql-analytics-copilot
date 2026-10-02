# AI SQL Analytics Copilot

The AI SQL Analytics Copilot turns natural-language fleet questions into safe, explainable SQL workflows. Its Next.js dashboard presents backend-validated results as conversations, KPIs, charts, tables, and generated SQL.

## Architecture

The system is a modular monolith: Next.js presentation layer -> FastAPI -> schema/business context -> Gemini or mock provider -> SQLGlot validation -> PostgreSQL read-only execution -> result intelligence. SQL generation, validation, metric definitions, summaries, and visualization selection remain backend-owned.

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

Without `.env`, the backend uses local SQLite defaults. Start it with `make dev`; the API is at http://localhost:8000. `GET /health` is liveness, `GET /health/ready` checks required databases/provider configuration, and development API docs are at `/docs`.

To use a configured PostgreSQL database, run `make migrate` and `make seed`. Seeding is deterministic and idempotent.

Run the frontend separately:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. Next.js proxies `/api/*` to `http://localhost:8000` by default, keeping browser calls same-origin. `INTERNAL_API_URL` changes the server-side proxy destination. The browser receives no provider or database credentials.

## APIs and Security

- `POST /api/v1/analytics/generate` generates SQL without executing it.
- `POST /api/v1/analytics/ask` generates, validates, executes, and returns result intelligence.
- `POST /api/v1/analytics/query` and `/validate` expose the internal direct-SQL surface.
- `GET /api/v1/metrics` returns process-local counters and latency averages.

Errors use `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`. Requests are size- and length-limited; generate/ask/conversation writes have configurable process-local rate limits. PostgreSQL statement timeout, row limits, table/column allowlists, dangerous-function restrictions, and AST validation remain enforced for generated and repaired SQL. Generated SQL is always untrusted.

The analytics DB uses a separate `analytics_readonly` role with a distinct password. Do not grant it writes or use application-owner credentials for analytics execution. See [docs/security.md](docs/security.md) for SQL controls and [docs/production-security-review.md](docs/production-security-review.md) for implemented controls versus recommended future controls. AST validation is defense in depth, not a complete security guarantee.

Set `LLM_MODE=gemini`, `GEMINI_API_KEY`, and `GEMINI_MODEL` for Gemini. Mock mode requires no key and is disabled in production. Provider failures are bounded and classified; generated SQL is never executed after provider failure.

## Docker Compose

Copy `.env.example` to `.env`, replace both owner and read-only password placeholders with distinct credentials, and keep `.env` out of Git. Initialize and seed the database before starting the application:

```bash
docker compose up -d postgres
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m app.db.seed
docker compose up --build -d
```

Dashboard: http://localhost:3000. API: http://localhost:8000. Compose waits for PostgreSQL and backend readiness. The backend container is non-root with a read-only root filesystem, and both application images have health checks. Stop with `docker compose down`; do not add `--volumes` unless deleting database state is intended.

The PostgreSQL init script sets the `analytics_readonly` password only for new clusters. Changing environment variables does not rotate credentials in an already-initialized database; rotate both roles explicitly and update both connection URLs.

## Configuration and Operations

`APP_ENV=production` disables debug/docs and rejects SQLite URLs and mock LLM mode. Configure exact `CORS_ALLOWED_ORIGINS` only when direct cross-origin browser access is required; the Next proxy is same-origin by default. Pool sizes, connection/query/provider timeouts, request limits, rate limits, repair attempts, and result caps are environment-configurable. Do not put real secrets in image build args, source control, or logs.

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

## Limitations

There is no authentication, tenant authorization, durable conversation storage, shared multi-instance rate limiter, or external metrics aggregation. Rate limits and metrics are process-local; the metrics endpoint is unauthenticated. Do not expose customer data as a public multi-tenant service without adding those controls. This is a production-oriented MVP, not an enterprise security certification. See [docs/deployment.md](docs/deployment.md) for deployment steps and operational caveats.
