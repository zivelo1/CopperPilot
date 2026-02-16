.PHONY: install install-dev test lint format serve serve-dev stop clean help

# Default Python — respects venv if activated
PYTHON ?= python3
PIP ?= pip

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime dependencies
	$(PIP) install -r requirements.txt

install-dev: ## Install runtime + development dependencies
	$(PIP) install -r requirements-dev.txt

test: ## Run test suite
	pytest tests/ -v

test-cov: ## Run tests with coverage report
	pytest tests/ --cov=workflow --cov=scripts -v --tb=short

lint: ## Run linting checks
	black --check .
	flake8 .

format: ## Auto-format code with Black
	black .

serve: ## Start production server
	./start_server.sh

serve-dev: ## Start development server with auto-reload
	./start_server.sh --dev

stop: ## Stop all running servers
	./stop_server.sh

clean: ## Remove generated artifacts
	find . -type d -name __pycache__ -not -path '*/venv/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.py[cod]' -not -path '*/venv/*' -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage
