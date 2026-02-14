.PHONY: dev build up down logs fmt lint test clean

dev:
	docker compose -f infra/docker-compose.yml up --build

build:
	docker compose -f infra/docker-compose.yml build

up:
	docker compose -f infra/docker-compose.yml up -d

down:
	docker compose -f infra/docker-compose.yml down

logs:
	docker compose -f infra/docker-compose.yml logs -f

fmt:
	cd apps/api && python -m black . && python -m isort .
	cd apps/web && npx prettier --write .

lint:
	cd apps/api && python -m ruff check .
	cd apps/web && npx eslint .

test:
	cd apps/api && python -m pytest tests/ -v

clean:
	docker compose -f infra/docker-compose.yml down -v --remove-orphans
	rm -rf apps/web/.next apps/web/node_modules
