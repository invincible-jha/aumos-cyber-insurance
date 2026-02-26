.PHONY: install dev lint typecheck test test-cov migrate docker-build docker-up docker-down clean

install:
	pip install -e ".[dev]"

dev:
	uvicorn aumos_cyber_insurance.main:app --reload --host 0.0.0.0 --port 8000

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

lint-fix:
	ruff check --fix src/ tests/
	ruff format src/ tests/

typecheck:
	mypy src/

test:
	pytest tests/ -v

test-cov:
	pytest tests/ -v --cov=aumos_cyber_insurance --cov-report=term-missing --cov-report=html

migrate:
	alembic -c src/aumos_cyber_insurance/migrations/alembic.ini upgrade head

migrate-down:
	alembic -c src/aumos_cyber_insurance/migrations/alembic.ini downgrade -1

docker-build:
	docker build -t aumos-cyber-insurance:latest .

docker-up:
	docker compose -f docker-compose.dev.yml up -d

docker-down:
	docker compose -f docker-compose.dev.yml down

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
