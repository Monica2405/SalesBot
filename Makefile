# Works with GNU Make on Linux/macOS and on Windows from Git Bash (make via `winget install ezwinports.make`).
# Recipes are plain POSIX sh: no bash-isms, no PowerShell.

ADMIN := apps/admin

.PHONY: help setup dev-api dev-agent dev-admin require-docker db-up db-down db-reset migrate test lint format load-clinic simulate-intake console

help:
	@echo "setup      install Python (uv) + admin (npm) deps and git hooks"
	@echo "dev-api    run FastAPI on http://localhost:8000 (reload)"
	@echo "dev-agent  run the voice agent with mock providers (text simulation)"
	@echo "dev-admin  run the admin app on http://localhost:5173"
	@echo "db-up      [requires Docker + Supabase CLI] start local Supabase"
	@echo "db-down    [requires Docker + Supabase CLI] stop local Supabase"
	@echo "db-reset   [requires Docker + Supabase CLI] recreate local DB from migrations + seed.sql"
	@echo "migrate    push migrations to the LINKED remote project (ask before linking)"
	@echo "test       Python tests (DB tests skip if Supabase is down) + admin build"
	@echo "lint       ruff + eslint + tsc"
	@echo "format     ruff format + fix"
	@echo "load-clinic FILE=x.yaml        load a clinic setup into SUPABASE_DB_URL (dev)"
	@echo "simulate-intake ARGS='...'     send a signed fake registration (dev, see INTAKE_CONTRACT)"
	@echo "console ARGS='--lang mr'       chat with the appointment flow in the terminal (no DB)"

setup:
	uv sync --all-packages
	npm --prefix $(ADMIN) install
	uv run pre-commit install

dev-api:
	uv run --package salesbot-api uvicorn salesbot_api.main:app --reload --port 8000

dev-agent:
	uv run --package salesbot-agent python -m salesbot_agent

dev-admin:
	npm --prefix $(ADMIN) run dev

# Local DB is deferred (docs/DECISIONS.md). These targets need Docker running and the Supabase CLI.
require-docker:
	@command -v supabase >/dev/null 2>&1 || { echo "ERROR: Supabase CLI not found. Install it (see README) and retry."; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "ERROR: Docker is not running. db-up/db-down/db-reset require Docker and the Supabase CLI."; echo "Start Docker Desktop, or use a hosted Supabase dev project instead (docs/DECISIONS.md)."; exit 1; }

db-up: require-docker
	supabase start

db-down: require-docker
	supabase stop

db-reset: require-docker
	supabase db reset

migrate:
	supabase db push

test:
	uv run pytest
	npm --prefix $(ADMIN) run build

lint:
	uv run ruff check .
	uv run ruff format --check .
	npm --prefix $(ADMIN) run lint

format:
	uv run ruff check --fix .
	uv run ruff format .

load-clinic:
	uv run --package salesbot-api python -m salesbot_api.tools.load_clinic $(FILE)

simulate-intake:
	uv run --package salesbot-api python -m salesbot_api.tools.simulate_intake $(ARGS)

console:
	uv run --package salesbot-api python -m salesbot_api.tools.console $(ARGS)
