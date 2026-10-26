# ==============================================================================
# Makefile — AI Support Chatbot Developer Automation
# ==============================================================================

.PHONY: help setup dev migrate ingest test test-unit test-integration test-security test-eval lint format docker-up docker-down clean

PYTHON ?= ./.venv/Scripts/python
PIP ?= ./.venv/Scripts/pip
PYTEST ?= ./.venv/Scripts/pytest
RUFF ?= ./.venv/Scripts/ruff
ALEMBIC ?= ./.venv/Scripts/alembic
UVICORN ?= ./.venv/Scripts/uvicorn

help:
	@echo "Available commands:"
	@echo "  make setup            Create venv and install dependencies"
	@echo "  make dev              Start the FastAPI development server"
	@echo "  make migrate          Run Alembic migrations to upgrade schema"
	@echo "  make ingest           Ingest demo FAQ knowledge documents"
	@echo "  make test             Run full test suite (unit, integration, security, eval)"
	@echo "  make test-unit        Run unit tests only"
	@echo "  make test-security    Run security & isolation tests"
	@echo "  make test-eval        Run RAG retrieval & grounding evaluation"
	@echo "  make lint             Run Ruff linter"
	@echo "  make format           Format code using Ruff"
	@echo "  make docker-up        Start services via Docker Compose"
	@echo "  make docker-down      Stop Docker Compose services"
	@echo "  make clean            Remove temporary files and caches"

setup:
	python -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

dev:
	$(UVICORN) app.main:app --reload --host 127.0.0.1 --port 8000

migrate:
	$(ALEMBIC) upgrade head

ingest:
	$(PYTHON) scripts/ingest_documents.py --tenant demo-company --file knowledge/demo_faq.md --approve

test:
	$(PYTEST) tests/ -v --cov=app --cov-report=term-missing

test-unit:
	$(PYTEST) tests/unit/ -v

test-integration:
	$(PYTEST) tests/integration/ -v

test-security:
	$(PYTEST) tests/security/ -v

test-eval:
	$(PYTEST) tests/evaluation/ -v

lint:
	$(RUFF) check app/ scripts/ tests/

format:
	$(RUFF) format app/ scripts/ tests/

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down -v

clean:
	rm -rf __pycache__ .pytest_cache .coverage htmlcov
