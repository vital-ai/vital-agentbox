.PHONY: install test test-all test-memfs test-spike test-box test-manager test-api test-reportgen test-gitbox test-git-sync test-orchestrator clean playwright serve docker-build pyodide-download help

PYTHON ?= python
PIP ?= pip

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install package in editable mode with dev + server extras
	$(PIP) install -e ".[dev,server]"

playwright: ## Install Chromium for Playwright
	$(PYTHON) -m playwright install chromium

serve: ## Start the FastAPI server (localhost:8000)
	$(PYTHON) -m uvicorn agentbox.api.app:app --host 0.0.0.0 --port 8000 --reload

test: ## Run shell executor tests (Tier 1 + Tier 2, 48 tests)
	$(PYTHON) test/test_shell_executor.py

test-memfs: ## Run MemFS tests
	$(PYTHON) test/test_memfs.py

test-box: ## Run CodeExecutorBox lifecycle tests (16 tests)
	$(PYTHON) test/test_box_lifecycle.py

test-manager: ## Run BoxManager tests (31 tests)
	$(PYTHON) test/test_box_manager.py

test-api: ## Run FastAPI endpoint tests (35 tests)
	$(PYTHON) test/test_api.py

test-spike: ## Run binary transfer + isomorphic-git spike
	$(PYTHON) test/test_spike_binary_and_git.py

test-reportgen: ## Run reportgen (Tier 3) tests (28 tests)
	$(PYTHON) test/test_reportgen.py

test-gitbox: ## Run GitBox (isomorphic-git) tests (40 tests)
	$(PYTHON) test/test_gitbox.py

test-git-sync: ## Run git sync (push/pull/clone + LocalStorage) tests (29 tests)
	$(PYTHON) test/test_git_sync.py

test-orchestrator: ## Run orchestrator state + auth tests (43 tests)
	$(PYTHON) test/test_orchestrator.py

test-all: test test-memfs test-box test-manager test-api test-reportgen test-gitbox test-git-sync test-orchestrator ## Run all test suites

pyodide-download: ## Download Pyodide bundle for local/Docker use
	bash scripts/download_pyodide.sh

docker-build: ## Build the worker Docker image
	docker build -f Dockerfile.worker -t agentbox-worker .

docs: ## Regenerate API reference docs from OpenAPI schemas
	$(PYTHON) scripts/generate_api_docs.py

release-test: clean ## Build and upload to TestPyPI
	$(PYTHON) -m build
	$(PYTHON) -m twine check dist/*
	$(PYTHON) -m twine upload --repository testpypi dist/*

release: clean ## Build and upload to PyPI
	$(PYTHON) -m build
	$(PYTHON) -m twine check dist/*
	$(PYTHON) -m twine upload dist/*

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info .eggs/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
