# NetKâr geliştirici komutları. Çalışma dizini: netkar/
SHELL := /bin/sh
API := services/api
ENV_FILE ?= infra/.env
COMPOSE := docker compose -f infra/docker-compose.yml

# infra/.env varsa ortama yükler (yerel çalıştırma için).
LOAD_ENV := set -a; if [ -f $(CURDIR)/$(ENV_FILE) ]; then . $(CURDIR)/$(ENV_FILE); fi; set +a;

.PHONY: help setup env lint test dev migrate worker db-up db-down web-lint web-test

help:
	@echo "setup  : Python bağımlılıklarını kurar (uv sync)"
	@echo "env    : infra/.env üretir (rastgele sırlarla), varsa dokunmaz"
	@echo "lint   : ruff check + ruff format --check + mypy"
	@echo "test   : pytest (gerçek PostgreSQL 16, kapsam raporlu)"
	@echo "db-up  : compose ile yalnız PostgreSQL'i başlatır"
	@echo "migrate: alembic upgrade head (DATABASE_MIGRATION_URL)"
	@echo "dev    : uvicorn (--reload)"
	@echo "worker : procrastinate worker"
	@echo "web-lint, web-test: apps/web için npm betikleri"

setup:
	cd $(API) && uv sync

env:
	@if [ -f $(ENV_FILE) ]; then echo "$(ENV_FILE) zaten var, dokunulmadı"; else \
	  owner=$$(openssl rand -hex 16); app=$$(openssl rand -hex 16); super=$$(openssl rand -hex 16); \
	  key=$$(openssl rand -base64 32); \
	  sed -e "s|REPLACE_ME_superuser|$$super|g" -e "s|REPLACE_ME_owner|$$owner|g" \
	      -e "s|REPLACE_ME_app|$$app|g" -e "s|REPLACE_ME_base64_32_bytes|$$key|g" \
	      infra/.env.example > $(ENV_FILE); chmod 600 $(ENV_FILE); echo "$(ENV_FILE) üretildi"; fi

lint:
	cd $(API) && uv run ruff check .
	cd $(API) && uv run ruff format --check .
	cd $(API) && uv run mypy

test:
	cd $(API) && uv run pytest --cov

db-up:
	$(COMPOSE) up -d postgres

db-down:
	$(COMPOSE) stop postgres

migrate:
	$(LOAD_ENV) cd $(API) && uv run alembic upgrade head

dev:
	$(LOAD_ENV) cd $(API) && uv run uvicorn app.main:create_app --factory --reload --port 8000

worker:
	$(LOAD_ENV) cd $(API) && uv run procrastinate --app=app.worker.app.app worker

web-lint:
	npm --prefix apps/web run lint

web-test:
	npm --prefix apps/web run test
