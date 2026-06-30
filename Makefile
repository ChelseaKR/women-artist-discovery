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

# Dependency-audit waivers (SECURITY-AND-SUPPLY-CHAIN-STANDARD §4 "Unfixable
# HIGH/CRITICAL waiver — committed, justified waiver JSON"). Every ID below is
# justified + tracked machine-readably in docs/audits/vex.json and narratively in
# docs/audits/residual-risk.md (RR-1, RR-4). Two clusters:
#   RR-1  GHSA-4xh5-x5gv-qwph — pip fallback tar extraction; pip is build-time
#         tooling, not a shipped runtime dep.
#   RR-4  every other ID — its FIRST fixed release is gated to Python >=3.10
#         (Python 3.9 reached EOL 2025-10), so on this repo's 3.9 floor NO fix is
#         pip-installable; forcing the pin would break `make install`. Remediation
#         is the Python 3.10+ migration flagged in docs/ROADMAP.md. Re-audit (drop
#         the relevant IDs) the moment the floor moves to 3.10 — the fixes are
#         already published there.
AUDIT_IGNORES := \
	--ignore-vuln GHSA-4xh5-x5gv-qwph \
	--ignore-vuln GHSA-w853-jp5j-5j7f \
	--ignore-vuln GHSA-qmgc-5h2g-mvrw \
	--ignore-vuln GHSA-6v7p-g79w-8964 \
	--ignore-vuln PYSEC-2026-165 \
	--ignore-vuln GHSA-cfh3-3jmp-rvhc \
	--ignore-vuln GHSA-whj4-6x5x-4v2j \
	--ignore-vuln GHSA-5xmw-vc9v-4wf2 \
	--ignore-vuln GHSA-r73j-pqj5-w3x7 \
	--ignore-vuln GHSA-pwv6-vv43-88gr \
	--ignore-vuln PYSEC-2026-196 \
	--ignore-vuln GHSA-58qw-9mgm-455v \
	--ignore-vuln GHSA-jp4c-xjxw-mgf9 \
	--ignore-vuln PYSEC-2026-113 \
	--ignore-vuln GHSA-6w46-j5rx-g56g \
	--ignore-vuln GHSA-gc5v-m9x4-r6x2 \
	--ignore-vuln PYSEC-2026-212 \
	--ignore-vuln GHSA-7p48-42j8-8846 \
	--ignore-vuln PYSEC-2026-142 \
	--ignore-vuln PYSEC-2026-141

security: ## Stage 4 — dependency vulnerability + secret scan
	# Audit installed deps; waived advisories are justified in docs/audits/vex.json.
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

audit: a11y eval ## Regenerate all committed responsible-tech artifacts
	$(PYTHON) -m pytest -q >/dev/null
	@echo "✓ audit artifacts regenerated under docs/audits/"

clean: ## Remove caches and generated local data
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage
	rm -f data/*.db
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
