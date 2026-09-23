.PHONY: dev test lint format docker-up docker-down

PYTHON ?= $(if $(wildcard backend/.venv/bin/python),.venv/bin/python,python3)

dev:
	cd backend && $(PYTHON) -m uvicorn app.main:app --reload

test:
	cd backend && $(PYTHON) -m pytest

lint:
	cd backend && $(PYTHON) -m ruff check .

format:
	cd backend && $(PYTHON) -m ruff format .

docker-up:
	docker compose up --build

docker-down:
	docker compose down
