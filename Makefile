UV ?= uv
NPM ?= npm

.PHONY: setup setup-api api web build check check-api check-web smoke contracts docker-api docker

setup:
	$(UV) sync --project backend --locked
	$(NPM) --prefix frontend ci

setup-api:
	$(UV) sync --project backend --locked

api:
	$(UV) run --project backend --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log

web:
	$(NPM) --prefix frontend run dev

build:
	$(NPM) --prefix frontend run build

check: check-api check-web

check-api:
	$(UV) run --project backend --locked ruff check backend contracts tools
	$(UV) run --project backend --locked ruff format --check backend contracts tools
	$(UV) run --project backend --locked python tools/export_contracts.py --check
	$(UV) run --project backend --locked pytest backend/tests

check-web:
	$(NPM) --prefix frontend run check
	$(NPM) --prefix frontend test
	$(NPM) --prefix frontend run build

smoke:
	$(UV) run --project backend --locked python tools/smoke_app.py

contracts:
	$(UV) run --project backend --locked python tools/export_contracts.py

docker-api:
	docker compose -f compose.api.yaml up --build

docker:
	docker compose up --build
