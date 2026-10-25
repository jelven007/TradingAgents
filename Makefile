PYTHON ?= python3
UV ?= uv
COMPOSE = docker compose --project-directory . --env-file .env -f deploy/docker/compose.yaml

.PHONY: install install-locked lint test test-system docs-check build check compose-build compose-run

install:
	$(PYTHON) -m pip install -e ".[dev]"

install-locked:
	$(UV) sync --frozen --extra dev --python $(PYTHON)

lint:
	$(PYTHON) -m ruff check .

test:
	$(PYTHON) -m pytest -q

test-system:
	$(PYTHON) -m pytest -q -m system

docs-check:
	$(PYTHON) scripts/check_docs.py

build:
	$(PYTHON) -m build

check: lint docs-check test build

compose-build:
	$(COMPOSE) build

compose-run:
	$(COMPOSE) run --rm tradingagents
