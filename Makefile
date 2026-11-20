.PHONY: init-local validate-examples validate-local verify-pluggy up down logs sync demo backup lint format test build-web

CONFIG_DIR ?= ./local

init-local:
	@./scripts/init_local.sh

validate-examples:
	uv run python scripts/validate_config.py --config-dir config/examples

validate-local:
	uv run python scripts/validate_config.py --config-dir $(CONFIG_DIR)

verify-pluggy:
	uv run python scripts/verify_pluggy.py --config-dir $(CONFIG_DIR)

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

sync:
	docker compose exec api python -m finops.worker.main --once

demo:
	docker compose exec api python -m finops.worker.main --seed-demo

backup:
	@./scripts/backup_db.sh

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

test:
	uv run pytest

build-web:
	cd apps/web && npm run build
