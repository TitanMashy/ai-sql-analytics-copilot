# AI SQL Analytics Copilot

The AI SQL Analytics Copilot is a modular monolith for turning natural-language analytics questions into safe, explainable SQL workflows. Sprint 1 establishes the backend, database, and developer tooling foundation.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the preliminary architecture diagram. LLM, SQL generation, analytics logic, and the frontend are intentionally deferred to later sprints.

## Technology Stack

- Python 3.12+
- FastAPI and Pydantic
- SQLAlchemy and psycopg
- PostgreSQL
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

## Testing and Linting

```bash
make test
make lint
```
