# Women-Artist Discovery — single source of truth for the local + CI gates.
# `make verify` runs the same checkable gates CI enforces (QUALITY-AND-METRICS
# STANDARD §"enforcement pipeline"), in order.

PYTHON ?= .venv/bin/python
PIP    ?= .venv/bin/pip
A11Y_HTML := docs/audits/dashboard.html

.DEFAULT_GOAL := help
.PHONY: help install dev verify format lint typecheck test security a11y eval audit clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(PYTHON): ## Bootstrap the virtualenv + dev/app deps
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e ".[dev,app]"

install: $(PYTHON) ## Install the project (editable) with dev + app extras

dev: install ## Run the Streamlit dashboard (demo mode; no API key needed)
	$(PYTHON) -m streamlit run app/dashboard.py

# --- The verify pipeline (each stage is merge-blocking) ----------------------
verify: lint typecheck test security a11y eval ## Run every checkable gate (CI parity)
	@echo "✓ all checkable gates green"

format: ## Auto-format the code
	$(PYTHON) -m ruff format .

lint: ## Stage 1 — format check + lint (ruff, incl. bandit SAST subset)
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m ruff check .

typecheck: ## Stage 2 — strict static typing (mypy --strict)
	$(PYTHON) -m mypy

test: ## Stage 3 — unit + integration tests with coverage gate (>=85%)
	$(PYTHON) -m pytest

security: ## Stage 4 — dependency vulnerability + secret scan
	# Audit installed deps. GHSA-4xh5-x5gv-qwph (CVE-2025-8869, pip fallback tar
	# extraction) has NO fixed version published and pip is build-time tooling, not
	# a shipped runtime dependency — accepted + tracked in docs/audits/residual-risk.md.
	$(PYTHON) -m pip_audit --skip-editable --ignore-vuln GHSA-4xh5-x5gv-qwph
	@./scripts/secret-scan.sh

a11y: ## Stage 5 — render the dashboard and run the a11y gate (0 violations)
	$(PYTHON) -m app.build_static
	@if command -v pa11y >/dev/null 2>&1; then \
		echo "running pa11y (axe runtime)"; pa11y --runner axe $(A11Y_HTML); \
	else \
		echo "pa11y not installed — using built-in static a11y checker"; \
		$(PYTHON) -m app.a11y_check $(A11Y_HTML); \
	fi

eval: ## Stage 7 — offline eval; fails unless the hybrid beats the baseline
	$(PYTHON) -m pipeline.cli eval --k 5 --out docs/audits/eval-report.json

audit: a11y eval ## Regenerate all committed responsible-tech artifacts
	$(PYTHON) -m pytest -q >/dev/null
	@echo "✓ audit artifacts regenerated under docs/audits/"

clean: ## Remove caches and generated local data
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage
	rm -f data/*.db
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
