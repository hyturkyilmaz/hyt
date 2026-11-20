# NetKâr geliştirici komutları. Çalışma dizini: netkar/
SHELL := /bin/sh
API := services/api
ENV_FILE ?= infra/.env
COMPOSE := docker compose -f infra/docker-compose.yml

# infra/.env varsa ortama yükler (yerel çalıştırma için).
LOAD_ENV := set -a; if [ -f $(CURDIR)/$(ENV_FILE) ]; then . $(CURDIR)/$(ENV_FILE); fi; set +a;

.PHONY: help setup env lint test test-seri test-profit test-alerts dev migrate worker seed-demo mark-non-prod db-up db-down web-lint web-test

help:
	@echo "setup  : Python bağımlılıklarını kurar (uv sync)"
	@echo "env    : infra/.env üretir (rastgele sırlarla), varsa dokunmaz"
	@echo "lint   : ruff check + ruff format --check + mypy"
	@echo "test   : pytest -n auto (xdist, işçi başına veritabanı; gerçek PostgreSQL 16, kapsam raporlu)"
	@echo "test-seri: aynı takım tek işlemde (hata ayıklama ve paralel/seri karşılaştırması için)"
	@echo "test-profit: kâr motoru testleri, app/profit satır ve dal kapsamı %100 (DB gerekmez)"
	@echo "test-alerts: uyarı kuralları (ADR-0009 D1) testleri, app/alerts satır ve dal kapsamı %100 (DB gerekmez)"
	@echo "db-up  : compose ile yalnız PostgreSQL'i başlatır"
	@echo "migrate: alembic upgrade head (DATABASE_MIGRATION_URL)"
	@echo "seed-demo: uydurma demo veri + doğru cevap kartı (NETKAR_ENV=local|test|staging ve SEED_ARGS ile; üretimde reddeder)"
	@echo "mark-non-prod: veritabanına 'üretim değil' işareti (ayrı provisioning adımı; DATABASE_ADMIN_URL, NETKAR_ENV ve MARK_ARGS=\"--confirm db@instance_id\" ile)"
	@echo "dev    : uvicorn (--reload)"
	@echo "worker : procrastinate worker"
	@echo "web-lint, web-test: apps/web için npm betikleri"

setup:
	cd $(API) && uv sync

env:
	@if [ -f $(ENV_FILE) ]; then echo "$(ENV_FILE) zaten var, dokunulmadı"; else \
	  owner=$$(openssl rand -hex 16); app=$$(openssl rand -hex 16); worker=$$(openssl rand -hex 16); super=$$(openssl rand -hex 16); \
	  key=$$(openssl rand -base64 32); \
	  sed -e "s|REPLACE_ME_superuser|$$super|g" -e "s|REPLACE_ME_owner|$$owner|g" \
	      -e "s|REPLACE_ME_app|$$app|g" -e "s|REPLACE_ME_worker|$$worker|g" -e "s|REPLACE_ME_base64_32_bytes|$$key|g" \
	      infra/.env.example > $(ENV_FILE); chmod 600 $(ENV_FILE); echo "$(ENV_FILE) üretildi"; fi

lint:
	cd $(API) && uv run ruff check .
	cd $(API) && uv run ruff format --check .
	cd $(API) && uv run mypy

# Paralel koşu: her xdist işçisi kendi veritabanını (ve yerelde kendi geçici kümesini) açar; kapsam otomatik birleşir.
test:
	cd $(API) && uv run pytest -n auto --maxprocesses=4 --cov

# Seri koşu (xdist yok): paralel modda yalnız görülen bir hatayı ayırt etmek için.
test-seri:
	cd $(API) && uv run pytest --cov

test-profit:
	cd $(API) && uv run pytest tests/test_profit_*.py --cov=app/profit --cov-branch --cov-fail-under=100 --cov-report=term-missing

# Uyarı kuralları (app/alerts) saftır; kâr motoru kapsam koşusundan ayrı, kendi %100 kapsam kapısıyla.
test-alerts:
	cd $(API) && uv run pytest tests/test_alerts_*.py --cov=app/alerts --cov-branch --cov-fail-under=100 --cov-report=term-missing

db-up:
	$(COMPOSE) up -d postgres

db-down:
	$(COMPOSE) stop postgres

migrate:
	$(LOAD_ENV) cd $(API) && uv run alembic upgrade head

dev:
	$(LOAD_ENV) cd $(API) && uv run uvicorn app.main:create_app --factory --reload --port 8000 --no-proxy-headers

# Demo veri tohumu (docs/ux/kullanici_testi_plani_S4.md §7.1). NETKAR_ENV açıkça verilmeden çalışmaz
# (koruma ayrıntısı: services/api/README.md "Demo veri tohumu"). Örnek:
#   NETKAR_ENV=local make seed-demo
#   NETKAR_ENV=local make seed-demo SEED_ARGS="--instance 2 --dataset x"
seed-demo:
	@test -n "$$NETKAR_ENV" || { echo "NETKAR_ENV (local, test ya da staging) verilmeli: NETKAR_ENV=local make seed-demo"; exit 3; }
	$(LOAD_ENV) cd $(API) && uv run python -m app.tools.seed_demo --demo $(SEED_ARGS)

# "Üretim değil" işareti tohumdan AYRI, bilinçli adımdır (denetim DT-14). Önce MARK_ARGS olmadan çalıştırın:
# sunucu kimliğini basar, hiçbir şey yazmaz. Sonra: make mark-non-prod MARK_ARGS="--confirm VERITABANI@INSTANCE_ID"
mark-non-prod:
	@test -n "$$NETKAR_ENV" || { echo "NETKAR_ENV (local, test ya da staging) verilmeli"; exit 3; }
	$(LOAD_ENV) cd $(API) && uv run python -m app.tools.seed_demo mark-non-prod $(MARK_ARGS)

worker:
	$(LOAD_ENV) cd $(API) && uv run procrastinate --app=app.worker.app.app worker --concurrency 4

web-lint:
	npm --prefix apps/web run lint

web-test:
	npm --prefix apps/web run test
