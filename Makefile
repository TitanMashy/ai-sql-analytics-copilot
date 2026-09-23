.PHONY: dev test lint format migrate seed verify-permissions docker-up docker-down

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
