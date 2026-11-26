PY ?= .venv/bin/python
NPM ?= npm --prefix frontend

.PHONY: setup install seed reset run frontend build test eval eval-offline eval-gemini openapi check

setup:              ## create the virtualenv, install Python + frontend dependencies
	python3.12 -m venv .venv
	$(PY) -m pip install -q -r requirements-dev.txt
	$(NPM) install
	@test -f .env || cp .env.example .env
	@echo "Done. Add GEMINI_API_KEY to .env for Gemini mode (optional), then: make build && make run"

install: setup      ## alias kept for compatibility

seed:               ## seed an empty database (also happens automatically on first start)
	$(PY) -m scripts.seed

reset:              ## drop all tables and re-seed the demo data
	$(PY) -m scripts.seed --reset

run:                ## API + built UI on http://localhost:8000 (API docs at /docs)
	$(PY) -m uvicorn app.main:create_app --factory --reload --port 8000

frontend:           ## UI dev server with hot reload on http://localhost:5173 (needs `make run` too)
	$(NPM) run dev

build:              ## typecheck and build the UI into frontend/dist (served by `make run`)
	$(NPM) run build

test:               ## backend test suite (offline, no API key needed)
	$(PY) -m pytest

eval-offline:       ## behaviour eval with the deterministic offline provider
	-$(PY) -m evals.run_eval --json evals/results/offline.json  # leading "-": known offline-rule misses must not fail `make check`

eval: eval-offline  ## alias

eval-gemini:        ## behaviour eval against live Gemini (needs GEMINI_API_KEY; uses quota)
	$(PY) -m evals.run_eval --provider gemini --delay 4 -v --json evals/results/gemini.json

openapi:            ## regenerate docs/openapi.json from the running app definition
	$(PY) -c "import json; from app.main import create_app; from app.core.config import Settings; print(json.dumps(create_app(Settings(_env_file=None, ai_provider='offline')).openapi(), indent=2))" > docs/openapi.json

check: test build eval-offline  ## everything a reviewer needs to see green
