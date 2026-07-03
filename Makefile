# Women-Artist Discovery — single source of truth for the local + CI gates.
# `make verify` runs the same checkable gates CI enforces (QUALITY-AND-METRICS
# STANDARD §"enforcement pipeline"), in order.

PYTHON ?= .venv/bin/python
PIP    ?= .venv/bin/pip
A11Y_HTML := docs/audits/dashboard.html

.DEFAULT_GOAL := help
.PHONY: help install dev verify format lint typecheck test security a11y eval i18n bench audit clean

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
verify: lint typecheck test security a11y eval i18n ## Run every checkable gate (CI parity)
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

# Dependency-audit waivers (SECURITY-AND-SUPPLY-CHAIN-STANDARD §4 "Unfixable
# HIGH/CRITICAL waiver — committed, justified waiver JSON").
# As of the Python 3.10+ migration (2026-06-30) the waiver list is EMPTY:
#   * RR-4 — the 19-advisory Python-3.9-EOL cluster (requests, urllib3, streamlit,
#     pillow, pyarrow, msgpack, filelock, pytest, pip) had fixes gated to
#     Python >=3.10; with the floor now >=3.10 every fix installs (see
#     pyproject floors + uv.lock), so all 19 IDs are dropped.
#   * RR-1 — GHSA-4xh5-x5gv-qwph (pip fallback tar extraction) is cleared by
#     pip>=25.3 / PEP 706 tar filter on the >=3.10 floor; no longer reported.
# `pip-audit` is therefore driven to 0 with NO --ignore-vuln flags. Re-introduce a
# justified entry here (byte-identical in ci.yml + docs/audits/vex.json) only if a
# genuinely-unfixable advisory ever appears. History: docs/audits/residual-risk.md.
AUDIT_IGNORES :=

security: ## Stage 4 — dependency vulnerability + secret scan
	# Audit installed deps; the waiver list is empty (see docs/audits/residual-risk.md).
	$(PYTHON) -m pip_audit --skip-editable $(AUDIT_IGNORES)
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

i18n: ## Stage 8 — i18n N/A declaration gate (INTERNATIONALIZATION-STANDARD §1)
	@./scripts/i18n-gate.sh

bench: ## Benchmark the scoring path on a generated 5k-artist / 50k-scrobble world
	$(PYTHON) scripts/bench.py

audit: a11y eval ## Regenerate all committed responsible-tech artifacts
	$(PYTHON) -m pytest -q >/dev/null
	@echo "✓ audit artifacts regenerated under docs/audits/"

clean: ## Remove caches and generated local data
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage
	rm -f data/*.db
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
