# AI SQL Analytics Copilot

The AI SQL Analytics Copilot is a modular monolith for turning natural-language analytics questions into safe, explainable SQL workflows. Sprint 3 adds the FastAPI analytics execution foundation over the migration-owned SaaS fleet-management dataset.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the preliminary architecture diagram and [docs/database-schema.md](docs/database-schema.md) for the database design. LLM, SQL generation, analytics logic, and the frontend are intentionally deferred to later sprints.

## Technology Stack

- Python 3.12+
- FastAPI and Pydantic
- SQLAlchemy and psycopg
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

The direct SQL API is an internal foundation for Sprint 4 and does not call OpenAI. It validates a single `SELECT`, executes through `ANALYTICS_DATABASE_URL` as `analytics_readonly`, normalizes database values to JSON, and enforces `MAX_RESULT_ROWS` and `QUERY_TIMEOUT_SECONDS`.

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

The current validator intentionally uses conservative placeholder checks. It is not a complete SQL security boundary; parser-backed validation, query policy enforcement, and stronger tenant isolation are Sprint 5 work.

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
