.PHONY: up down logs test lint migrate seed shell

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

test:
	pytest

lint:
	ruff check .
	mypy app

migrate:
	alembic upgrade head

seed:
	python scripts/seed_dev_data.py

shell:
	docker compose exec api /bin/bash
