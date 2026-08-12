.PHONY: install test lint format check up down logs migrate seed
install:
	python3 -m venv .venv
	.venv/bin/pip install -e '.[dev]'
test:
	.venv/bin/pytest
lint:
	.venv/bin/ruff check .
format:
	.venv/bin/ruff format .
check:
	.venv/bin/ruff format --check .
	.venv/bin/ruff check .
	.venv/bin/mypy app
	.venv/bin/pytest
up:
	docker compose up -d --build
down:
	docker compose down
logs:
	docker compose logs -f
migrate:
	docker compose run --rm bist-radar-api alembic upgrade head
seed:
	.venv/bin/python scripts/generate_fixtures.py
