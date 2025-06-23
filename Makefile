# GenAI Tag DB Tools Makefile
# Development task automation

.PHONY: help test lint format install install-dev clean run-gui setup

# Default target
help:
	@echo "GenAI Tag DB Tools - Available Commands:"
	@echo ""
	@echo "Development:"
	@echo "  setup        Setup cross-platform development environment"
	@echo "  install      Install project dependencies"
	@echo "  install-dev  Install development dependencies"
	@echo "  run-gui      Run Tag DB GUI application"
	@echo "  test         Run tests"
	@echo "  test-unit    Run unit tests only"
	@echo "  test-gui     Run GUI tests only"
	@echo "  test-cov     Run tests with coverage report"
	@echo "  lint         Run code linting (ruff)"
	@echo "  format       Format code (ruff format)"
	@echo "  typecheck    Run type checking (mypy)"
	@echo "  clean        Clean build artifacts"

# Setup target
setup:
	@echo "Setting up development environment..."
	./scripts/setup.sh

# Development targets
install:
	@echo "Installing project dependencies..."
	UV_PROJECT_ENVIRONMENT=.venv_linux uv sync

install-dev:
	@echo "Installing development dependencies..."
	UV_PROJECT_ENVIRONMENT=.venv_linux uv sync --dev

run-gui:
	@echo "Running Tag DB GUI..."
	@if [ "$(OS)" = "Windows_NT" ]; then \
		echo "Detected Windows environment"; \
		export UV_PROJECT_ENVIRONMENT=.venv_windows && uv run tag-db; \
	else \
		echo "Detected Unix/Linux environment"; \
		UV_PROJECT_ENVIRONMENT=.venv_linux uv run tag-db; \
	fi

# Testing targets
test:
	@echo "Running all tests..."
	UV_PROJECT_ENVIRONMENT=.venv_linux uv run pytest

test-unit:
	@echo "Running unit tests..."
	UV_PROJECT_ENVIRONMENT=.venv_linux uv run pytest -m unit

test-gui:
	@echo "Running GUI tests..."
	UV_PROJECT_ENVIRONMENT=.venv_linux uv run pytest -m gui

test-cov:
	@echo "Running tests with coverage..."
	UV_PROJECT_ENVIRONMENT=.venv_linux uv run pytest --cov=src --cov-report=html --cov-report=xml

# Code quality targets
lint:
	@echo "Running code linting..."
	UV_PROJECT_ENVIRONMENT=.venv_linux uv run ruff check

format:
	@echo "Formatting code..."
	UV_PROJECT_ENVIRONMENT=.venv_linux uv run ruff format
	UV_PROJECT_ENVIRONMENT=.venv_linux uv run ruff check --fix

typecheck:
	@echo "Running type checking..."
	UV_PROJECT_ENVIRONMENT=.venv_linux uv run mypy src/

# Cleanup target
clean:
	@echo "Cleaning build artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	@rm -rf build/ dist/ *.egg-info
	@echo "Build artifacts cleaned."