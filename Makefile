# Women-Artist Discovery — single source of truth for the local + CI gates.
# `make verify` runs the same checkable gates CI enforces (QUALITY-AND-METRICS
# STANDARD §"enforcement pipeline"), in order.

PYTHON ?= .venv/bin/python
UV     ?= uv
A11Y_HTML := docs/audits/dashboard.html

.DEFAULT_GOAL := help
.PHONY: help install dev verify format lint typecheck test security a11y eval eval-real i18n audit clean

# eval-real inputs (FIX-06's human-gated real-data leg — LOCAL ONLY, never CI).
EVAL_REAL_USER ?=
EVAL_REAL_DB ?=

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# Bootstraps from uv.lock (CQ-09/SEC-13): `--frozen` refuses to update the lock,
# so this is also the local lockfile-drift check — if pyproject.toml and uv.lock
# have drifted apart, this fails loudly instead of silently re-resolving.
$(PYTHON): pyproject.toml uv.lock ## Bootstrap the virtualenv + dev/app deps from uv.lock (uv sync --frozen)
	$(UV) sync --frozen --group dev --extra app
	touch $(PYTHON)

install: $(PYTHON) ## Install the project (editable) with dev + app extras, pinned via uv.lock

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
	@# CQ-34: locks in the currently-clean state — fails on any bare TODO/FIXME/HACK
	@# marker or unqualified `# noqa` (a qualified `# noqa: CODE` is fine and is
	@# ruff's own job to police via RUF100 "unused noqa").
	@if grep -rInE "TODO|FIXME|HACK" pipeline recommender app export tests scripts 2>/dev/null; then \
		echo "lint: bare TODO/FIXME/HACK marker found (CQ-34) — resolve or file a tracked issue" >&2; exit 1; \
	fi
	@if grep -rInE "#\s*noqa\s*($$|[^:])" pipeline recommender app export tests 2>/dev/null; then \
		echo "lint: blanket '# noqa' with no rule code found (CQ-35) — qualify it" >&2; exit 1; \
	fi
	@# DOC-08: CITATION.cff must stay schema-valid. Version-pinned (not bare
	@# `uvx cffconvert`) so this merge-blocking check doesn't drift silently.
	uvx cffconvert==2.0.0 --validate
	@# DOC-15: every governance/audit doc carries a currency stamp.
	@./scripts/check-staleness.sh

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
		echo "running pa11y (axe runtime)"; \
		printf '%s\n' '{"chromeLaunchConfig":{"args":["--no-sandbox"]}}' > /tmp/pa11y-ci.json; \
		pa11y --runner axe --config /tmp/pa11y-ci.json $(A11Y_HTML); \
	else \
		echo "pa11y not installed — using built-in static a11y checker"; \
		$(PYTHON) -m app.a11y_check $(A11Y_HTML); \
	fi

eval: ## Stage 7 — multi-world offline eval; fails unless hybrid beats baseline on aggregate (FIX-06)
	$(PYTHON) -m pipeline.cli eval --k 5 --out docs/audits/eval-report.json

# NOT part of verify/audit, and must NEVER run in CI (FIX-06's human-gated
# real-data leg — see recommender/eval.py::eval_real). Run locally only, on
# your own cache DB, e.g.:
#   make eval-real EVAL_REAL_USER=yourname EVAL_REAL_DB=data/cache.db
eval-real: ## LOCAL-ONLY — real-data eval leg against your own cached scrobbles; never CI
	@test -n "$(EVAL_REAL_USER)" || { echo "usage: make eval-real EVAL_REAL_USER=<lastfm-username> EVAL_REAL_DB=<path-to-cache.db>"; exit 1; }
	@test -n "$(EVAL_REAL_DB)" || { echo "usage: make eval-real EVAL_REAL_USER=<lastfm-username> EVAL_REAL_DB=<path-to-cache.db>"; exit 1; }
	$(PYTHON) -m pipeline.cli eval-real --user "$(EVAL_REAL_USER)" --scrobbles "$(EVAL_REAL_DB)"

i18n: ## Stage 8 — i18n N/A declaration gate (INTERNATIONALIZATION-STANDARD §1)
	@./scripts/i18n-gate.sh

audit: a11y eval ## Regenerate all committed responsible-tech artifacts
	$(PYTHON) -m pytest -q >/dev/null
	@echo "✓ audit artifacts regenerated under docs/audits/"

clean: ## Remove caches and generated local data
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov .coverage
	rm -f data/*.db
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
