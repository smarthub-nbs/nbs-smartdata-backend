SHELL := /bin/sh

SRC_DIR := src
DOCKER_ENV := .env.docker
LOCAL_ENV := .env
COMPOSE := docker compose --env-file $(DOCKER_ENV)
UV := uv
PYTHON := $(UV) run python
MANAGE := $(PYTHON) manage.py
CELERY := $(UV) run celery
SCHEMA_FILE ?= /tmp/smarthub-schema.yml
HOST ?= 127.0.0.1
PORT ?= 8000
APP ?=
MIGRATION ?=
TEST ?=
ARGS ?=

.DEFAULT_GOAL := help

.PHONY: help \
	env env-docker \
	install install-frozen check migrate makemigrations seed-roles superuser runserver shell test schema collectstatic celery import-dataset-files sqlmigrate showmigrations dbshell \
	docker-build docker-up docker-up-core docker-up-pgadmin docker-down docker-down-volumes docker-ps docker-logs docker-logs-web docker-logs-celery docker-restart-web docker-restart-celery \
	docker-migrate docker-makemigrations docker-seed-roles docker-superuser docker-shell docker-test docker-schema docker-collectstatic docker-import-dataset-files

help: ## Show available commands.
	@awk 'BEGIN {FS = ":.*##"; printf "\nSmarthub commands\n\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-28s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\nExamples:\n"
	@printf "  make docker-up\n"
	@printf "  make migrate\n"
	@printf "  make test TEST=djapps.datasets.tests.DatasetWorkflowTests\n"
	@printf "  make makemigrations APP=datasets\n\n"

env: ## Create local .env from .env.example if missing.
	@if [ -f "$(LOCAL_ENV)" ]; then \
		echo "$(LOCAL_ENV) already exists"; \
	else \
		cp .env.example "$(LOCAL_ENV)"; \
		echo "Created $(LOCAL_ENV) from .env.example"; \
	fi

env-docker: ## Create .env.docker from .env.docker.example if missing.
	@if [ -f "$(DOCKER_ENV)" ]; then \
		echo "$(DOCKER_ENV) already exists"; \
	else \
		cp .env.docker.example "$(DOCKER_ENV)"; \
		echo "Created $(DOCKER_ENV) from .env.docker.example"; \
	fi

install: ## Install local dependencies with uv.
	cd $(SRC_DIR) && $(UV) sync

install-frozen: ## Install local dependencies exactly from uv.lock.
	cd $(SRC_DIR) && $(UV) sync --frozen

check: ## Run Django system checks locally.
	cd $(SRC_DIR) && $(MANAGE) check

migrate: ## Apply database migrations locally.
	cd $(SRC_DIR) && $(MANAGE) migrate

makemigrations: ## Create migrations locally. Optionally pass APP=datasets.
	cd $(SRC_DIR) && $(MANAGE) makemigrations $(APP)

seed-roles: ## Seed authorization groups and permissions locally.
	cd $(SRC_DIR) && $(MANAGE) seed_roles

superuser: ## Create a Django superuser locally.
	cd $(SRC_DIR) && $(MANAGE) createsuperuser

runserver: ## Start local Django development server. Override HOST/PORT if needed.
	cd $(SRC_DIR) && $(MANAGE) runserver $(HOST):$(PORT)

shell: ## Open local Django shell.
	cd $(SRC_DIR) && $(MANAGE) shell

test: ## Run tests locally. Optionally pass TEST=djapps.datasets.tests.
	cd $(SRC_DIR) && $(MANAGE) test $(TEST)

schema: ## Validate and export OpenAPI schema locally.
	cd $(SRC_DIR) && $(MANAGE) spectacular --validate --file $(SCHEMA_FILE)

collectstatic: ## Collect static files locally.
	cd $(SRC_DIR) && $(MANAGE) collectstatic --noinput

celery: ## Start local Celery worker.
	cd $(SRC_DIR) && $(CELERY) -A config worker -l info

import-dataset-files: ## Import files from config/media/dataset_files locally.
	cd $(SRC_DIR) && $(MANAGE) import_dataset_files $(ARGS)

showmigrations: ## Show local migration status.
	cd $(SRC_DIR) && $(MANAGE) showmigrations $(APP)

sqlmigrate: ## Show SQL for a migration. Usage: make sqlmigrate APP=datasets MIGRATION=0018
	@if [ -z "$(APP)" ] || [ -z "$(MIGRATION)" ]; then \
		echo "Usage: make sqlmigrate APP=<app_name> MIGRATION=<migration_number>"; \
		exit 1; \
	fi
	cd $(SRC_DIR) && $(MANAGE) sqlmigrate $(APP) $(MIGRATION)

dbshell: ## Open local configured database shell.
	cd $(SRC_DIR) && $(MANAGE) dbshell

docker-build: ## Build Docker application image.
	$(COMPOSE) build

docker-up: ## Start Django, PostgreSQL, Redis, and Celery in Docker.
	$(COMPOSE) up -d web celery_worker

docker-up-core: ## Start only PostgreSQL and Redis in Docker.
	$(COMPOSE) up -d postgres redis

docker-up-pgadmin: ## Start pgAdmin in Docker.
	$(COMPOSE) up -d pgadmin

docker-down: ## Stop Docker services.
	$(COMPOSE) down

docker-down-volumes: ## Stop Docker services and remove local volumes.
	$(COMPOSE) down -v

docker-ps: ## Show Docker Compose service status.
	$(COMPOSE) ps

docker-logs: ## Follow logs for all Docker services.
	$(COMPOSE) logs -f

docker-logs-web: ## Follow Django web container logs.
	$(COMPOSE) logs -f web

docker-logs-celery: ## Follow Celery worker container logs.
	$(COMPOSE) logs -f celery_worker

docker-restart-web: ## Restart Docker web service.
	$(COMPOSE) restart web

docker-restart-celery: ## Restart Docker Celery worker.
	$(COMPOSE) restart celery_worker

docker-migrate: ## Apply migrations in Docker.
	$(COMPOSE) --profile tools run --rm migrate

docker-makemigrations: ## Create migrations in Docker. Optionally pass APP=datasets.
	$(COMPOSE) run --rm web python manage.py makemigrations $(APP)

docker-seed-roles: ## Seed authorization groups and permissions in Docker.
	$(COMPOSE) run --rm web python manage.py seed_roles

docker-superuser: ## Create a Django superuser in Docker.
	$(COMPOSE) run --rm web python manage.py createsuperuser

docker-shell: ## Open Django shell in Docker.
	$(COMPOSE) run --rm web python manage.py shell

docker-test: ## Run tests in Docker. Optionally pass TEST=djapps.datasets.tests.
	$(COMPOSE) run --rm web python manage.py test $(TEST)

docker-schema: ## Validate and export OpenAPI schema in Docker.
	$(COMPOSE) run --rm web python manage.py spectacular --validate --file /tmp/schema.yml

docker-collectstatic: ## Collect static files in Docker.
	$(COMPOSE) --profile tools run --rm collectstatic

docker-import-dataset-files: ## Import files from config/media/dataset_files in Docker.
	$(COMPOSE) run --rm web python manage.py import_dataset_files $(ARGS)
