# AI SQL Analytics Copilot

The AI SQL Analytics Copilot is a modular monolith for turning natural-language analytics questions into safe, explainable SQL workflows. Sprint 4 adds schema-aware natural-language SQL generation with deterministic mock and optional Gemini providers.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the architecture diagram, [docs/database-schema.md](docs/database-schema.md) for the database design, and [docs/business-definitions.md](docs/business-definitions.md) for metric definitions. The frontend and AST security layer remain deferred.

## Technology Stack

- Python 3.12+
- FastAPI and Pydantic
- SQLAlchemy and psycopg
- Google Gemini SDK with a provider abstraction
- PostgreSQL
- Alembic migrations
- pytest and Ruff
- Docker Compose

## Local Setup

Create a virtual environment and install the backend development dependencies:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` when you need to customize environment values. The application has local SQLite defaults, so the API can also be run without a `.env` file:

```bash
make dev
```

The API is available at http://localhost:8000 and the health endpoint is http://localhost:8000/api/v1/health.

To create the schema and deterministic demo dataset against the configured database:

```bash
make migrate
make seed
```

Running `make seed` again is idempotent and reports `already seeded`.

## Analytics API

The direct SQL API is an internal execution surface and does not call Gemini. It parses SQL with SQLGlot, enforces the application-table allowlist and read-only rules, executes through `ANALYTICS_DATABASE_URL` as `analytics_readonly`, normalizes database values to JSON, and enforces result, timeout, and complexity limits.

Validate a query:

```bash
curl -X POST http://localhost:8000/api/v1/analytics/validate \
	-H 'Content-Type: application/json' \
	-d '{"sql":"SELECT COUNT(*) AS active_vehicles FROM vehicles WHERE status = '\''active'\''"}'
```

Execute a query:

```bash
curl -X POST http://localhost:8000/api/v1/analytics/query \
	-H 'Content-Type: application/json' \
	-d '{"sql":"SELECT COUNT(*) AS active_vehicles FROM vehicles WHERE status = '\''active'\''"}'
```

The response contains `columns`, JSON-safe `rows`, `row_count`, and `execution_time_ms`. Rejected queries return a structured `error` object. Schema metadata is available at `/api/v1/schema`, `/api/v1/schema/tables`, and `/api/v1/schema/tables/{table_name}`. Interactive OpenAPI documentation is available at `/docs`.

Example analytics SQL is defined in [backend/app/sql/examples.py](backend/app/sql/examples.py), including revenue, utilization, idle time, fuel, and maintenance queries.

See [docs/security.md](docs/security.md) for the threat model and validation rules. AST validation is defense in depth, not a guarantee; database privileges and future tenant isolation remain essential.

## Natural-Language API

Mock mode works without an API key and is the default. It supports representative fleet questions and returns SQL without executing it:

```bash
curl -X POST http://localhost:8000/api/v1/analytics/generate \
	-H 'Content-Type: application/json' \
	-d '{"question":"What were the top 10 customers by revenue?"}'
```

The optional combined endpoint generates SQL, sends it through the existing validator, executes it through the read-only analytics database, and adds deterministic KPI, visualization, warning, and summary metadata:

```bash
curl -X POST http://localhost:8000/api/v1/analytics/ask \
	-H 'Content-Type: application/json' \
	-d '{"question":"What is the total number of active vehicles?"}'
```

Set `LLM_MODE=gemini`, `GEMINI_API_KEY`, and `GEMINI_MODEL` to use the official Google Gemini provider. Gemini structured output is parsed through the existing response parser. Provider output is untrusted: `tables_used`, confidence, and generated SQL never bypass validation. The generation prompt contains only relevant schema metadata and business definitions, never credentials or database URLs.

The `/ask` response is frontend-ready: `kpi` is returned for single aggregate values, `visualization` is selected deterministically from result shape, `warnings` covers empty or low-quality data, and `summary` is grounded in the returned rows. Set `ENABLE_RESULT_SUMMARY=false` to disable summaries without affecting SQL execution.

## Docker

Start PostgreSQL and the backend with:

```bash
docker compose up --build
```

Stop the services with:

```bash
docker compose down
```

The Compose setup waits for PostgreSQL to become healthy before starting the backend.
The PostgreSQL initialization script creates `analytics_readonly`; it receives `SELECT` on application tables through default privileges and is not granted write or DDL permissions.

## Testing and Linting

```bash
make test
make lint
```
