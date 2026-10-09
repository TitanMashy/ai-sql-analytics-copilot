.PHONY: dev test lint format typecheck coverage fuzz migrate seed verify-permissions \
	docker-up docker-down lock lock-check eval eval-check loadtest purge backup restore-drill

PYTHON ?= $(if $(wildcard backend/.venv/bin/python),.venv/bin/python,python3)

dev:
	cd backend && $(PYTHON) -m uvicorn app.main:app --reload

test:
	cd backend && $(PYTHON) -m pytest

lint:
	cd backend && $(PYTHON) -m ruff check .

format:
	cd backend && $(PYTHON) -m ruff format .

migrate:
	cd backend && $(PYTHON) -m alembic upgrade head

seed:
	cd backend && $(PYTHON) -m app.db.seed

verify-permissions:
	docker compose exec -T postgres psql -U app -d app -v ON_ERROR_STOP=1 -f /dev/stdin < database/verify-readonly.sql

docker-up:
	docker compose up --build

docker-down:
	docker compose down

typecheck:
	cd backend && $(PYTHON) -m mypy

coverage:
	cd backend && $(PYTHON) -m pytest -m "not integration" --cov=app --cov-report=term --cov-report=json:coverage.json
	cd backend && $(PYTHON) scripts/check_coverage.py coverage.json

# Longer, randomized validator run; the scheduled job uses 20000.
fuzz:
	cd backend && FUZZ_ITERATIONS=$${FUZZ_ITERATIONS:-5000} $(PYTHON) -m pytest -m fuzz -q

# Hash-pinned dependency lock generated from pyproject.toml. Commit backend/requirements.lock.
lock:
	cd backend && $(PYTHON) -m pip install pip-tools && $(PYTHON) -m piptools compile --generate-hashes --strip-extras --output-file=requirements.lock pyproject.toml

lock-check:
	cd backend && $(PYTHON) -m piptools compile --generate-hashes --strip-extras --quiet --output-file=/tmp/requirements.lock pyproject.toml && diff -u requirements.lock /tmp/requirements.lock

# Text-to-SQL evaluation (needs a migrated and seeded PostgreSQL; see docs/evaluation.md).
eval-check:
	cd backend && $(PYTHON) -m evals.run_eval --check-references

eval:
	cd backend && $(PYTHON) -m evals.run_eval --provider $${PROVIDER:-mock} $${SUBSET:+--subset $$SUBSET}

loadtest:
	k6 run -e BASE_URL=$${BASE_URL:-http://localhost:8000} loadtest/ask.js

purge:
	docker compose --profile ops run --rm purge

backup:
	scripts/backup_postgres.sh

restore-drill:
	scripts/restore_drill.sh
