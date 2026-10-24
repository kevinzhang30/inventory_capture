# Inventory Capture — developer entry points. `make help` lists targets.
SHELL := /bin/bash
PY := .venv/bin/python
PYTEST := .venv/bin/pytest
COMPOSE := docker compose -f local/docker-compose.yml
TF_DIR := infra/envs/dev
TF := terraform -chdir=$(TF_DIR)
API ?= http://localhost:8080
PY_DIRS := libs services local/gateway eval loadtest/simulator apps/desktop db
SERVICE_PKGS := $(foreach s,$(wildcard services/*),$(s)/$(notdir $(s)))

.PHONY: help install up down infra logs ps migrate seed bootstrap lint typecheck test test-integration smoke \
        web desktop simulate latency-probe loadtest-ingest loadtest-stock loadtest-search chaos verify \
        rebuild-cache rebuild-index eval-golden eval-run build-lambdas dev-init dev-plan dev-up dev-down

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Create .venv and install all Python packages (WITH_DESKTOP=1 for the PySide6 app)
	scripts/dev_install.sh

# ---------------------------------------------------------------- local stack
up: ## Build and start the full local stack (infra + all services)
	$(COMPOSE) --profile app up -d --build
	@echo "waiting for gateway..."; for i in $$(seq 1 90); do curl -fs $(API)/health >/dev/null && break; sleep 2; done
	@curl -fs $(API)/health && echo " gateway up at $(API)"

down: ## Stop the local stack and delete its volumes
	$(COMPOSE) --profile app --profile web --profile tools down -v --remove-orphans

infra: ## Start only the data stores (run services on the host)
	$(COMPOSE) up -d postgres kafka rabbitmq valkey opensearch s3

logs: ## Tail app logs (SVC=extract to filter)
	$(COMPOSE) --profile app logs -f --tail=100 $(SVC)

ps:
	$(COMPOSE) --profile app ps

migrate: ## Run Alembic migrations against DATABASE_URL
	$(PY) -m ops.bootstrap migrate

seed: ## Seed the demo catalog
	$(PY) -m ops.bootstrap seed

bootstrap: ## bucket + migrate + topics + rabbitmq + indices + seed (host, against `make infra`)
	$(PY) -m ops.bootstrap bucket migrate topics rabbitmq indices seed

# ---------------------------------------------------------------- quality
lint: ## ruff + eslint
	.venv/bin/ruff check $(PY_DIRS)
	cd apps/web && npm run lint

typecheck: ## mypy + tsc
	.venv/bin/mypy libs/common/inventory_common $(SERVICE_PKGS)
	cd apps/web && npm run typecheck

test: ## Unit tests (no infrastructure)
	$(PYTEST) -m "not integration" -p no:cacheprovider libs services local/gateway eval loadtest/simulator
	PYTHONPATH=apps/desktop $(PYTEST) apps/desktop/tests

test-integration: ## Integration tests against `make up`
	DATABASE_URL=postgresql://inventory:inventory@localhost:5432/inventory $(PYTEST) -m integration libs services

smoke: ## Scan → stock visible end to end
	API=$(API) local/scripts/smoke.sh

# ---------------------------------------------------------------- apps
web: ## Next.js dev server against the local gateway
	cd apps/web && { [ -d node_modules ] || npm ci; } && API_BASE_URL=$(API) AUTH_MODE=dev npm run dev

desktop: ## Run the desktop capture app (needs `WITH_DESKTOP=1 make install`)
	$(PY) -m inventory_desktop.main

# ---------------------------------------------------------------- load, chaos, eval
simulate: ## Modest simulator run (RATE, STATIONS, DURATION overridable)
	$(PY) -m simulator.run --api $(API) --stations $${STATIONS:-10} --rate $${RATE:-200} --duration $${DURATION:-60} --doc-ratio $${DOC_RATIO:-0.02}

latency-probe: ## Scan → visible latency percentiles
	$(PY) -m simulator.latency_probe --api $(API) --samples $${SAMPLES:-50}

K6 := $(shell command -v k6 2>/dev/null || echo "docker run --rm -i --network host -v $(CURDIR)/loadtest/k6:/scripts -w /scripts grafana/k6:0.54.0")
K6_DIR := $(if $(shell command -v k6 2>/dev/null),loadtest/k6,.)

loadtest-ingest: ## k6: 2000 captures/s for DURATION (default 10m)
	$(K6) run -e K6_API=$(API) $(K6_DIR)/ingest.js

loadtest-stock: ## k6: stock reads
	$(K6) run -e K6_API=$(API) $(K6_DIR)/stock_reads.js

loadtest-search: ## k6: search
	$(K6) run -e K6_API=$(API) $(K6_DIR)/search.js

chaos: ## SIGKILL random consumers while load runs (DURATION, INTERVAL)
	local/scripts/chaos.sh

verify: ## Ledger consistency checks (expect zero rows)
	local/scripts/verify.sh

rebuild-cache: ## Drop and warm the Redis stock cache from Postgres
	$(PY) -m ops.rebuild cache --warm

rebuild-index: ## Rebuild OpenSearch indices into VERSION and swap aliases
	$(PY) -m ops.rebuild index --version $${VERSION:?set VERSION=2}

eval-golden: ## Generate the synthetic golden set
	$(PY) -m evalkit.generate_golden --out eval/golden --count $${COUNT:-100}

eval-run: ## Evaluate EXTRACTOR (stub|bedrock) on the golden set
	$(PY) -m evalkit.run --extractor $${EXTRACTOR:-stub} --golden eval/golden --report eval/reports/$$(date +%Y%m%d-%H%M).md

# ---------------------------------------------------------------- AWS dev (Terraform)
build-lambdas: ## Build dist/lambda/*.zip for arm64 / Python 3.12
	scripts/build_lambdas.sh

dev-init:
	$(TF) init -backend-config=backend.hcl

dev-plan: build-lambdas dev-init ## terraform plan for dev
	$(TF) plan -var relay_image=$${RELAY_IMAGE:-public.ecr.aws/docker/library/python:3.12-slim}

dev-up: build-lambdas dev-init ## Create/update the AWS dev environment (ECR first, then image, then everything)
	$(TF) apply -auto-approve -target=module.ecs_relay.aws_ecr_repository.this
	ECR_URL=$$($(TF) output -raw relay_ecr_repository_url); \
	IMAGE=$$(scripts/build_relay_image.sh $$ECR_URL | tail -1); \
	$(TF) apply -auto-approve -var relay_image=$$IMAGE
	$(TF) output

dev-down: dev-init ## Destroy the AWS dev environment
	$(TF) destroy -auto-approve -var relay_image=destroy
