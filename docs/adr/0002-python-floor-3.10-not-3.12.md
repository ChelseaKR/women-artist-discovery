# 0002. Keep the Python floor at 3.10, not 3.12

Date: 2026-07-05

## Status

Accepted (short-term; revisit)

## Context

`CODE-QUALITY-STANDARD.md` sets a `>=3.12` floor recommendation; this repo's `requires-python` is
`>=3.10` (`pyproject.toml`). The 3.9 → 3.10 migration (commit `89344d6`, 2026-06-30) was a real,
deliberate security fix: it cleared a 19-advisory dependency cluster whose fixes were all gated to
Python ≥3.10 (see `docs/audits/residual-risk.md` RR-4). Moving straight to `>=3.12` in the same
pass would have been a second, unrelated migration bundled into a security fix — exactly the kind
of scope-creep the project's own change-hygiene practice (`docs/ROADMAP.md` build logs) avoids
elsewhere.

The `>=3.10` floor also forces a real workaround: `pyproject.toml`'s mypy config skips following
`streamlit`'s bundled stubs (`follow_imports = "skip"` on `streamlit.*`) because those stubs use
PEP 695 `type` aliases that need a `>=3.12` mypy target.

## Decision

Keep `requires-python = ">=3.10"` for now. Add `.python-version` pinning `3.13` as the **local dev
default** (the CI matrix already covers 3.10–3.13, so this doesn't reduce coverage — it just picks
which version a fresh `make install`/`uv sync` uses by default). Track raising the floor to
`>=3.12` (which would let the mypy streamlit workaround be removed) as separate, deliberate future
work, not bundled into this remediation pass.

## Consequences

- The `follow_imports = "skip"` mypy workaround for `streamlit.*` stays until a future `>=3.12`
  migration.
- `CQ-01` (Code Quality Standard's `>=3.12` floor control) remains a documented, dated gap rather
  than a silent one — this ADR is that documentation, satisfying `CQ-45`'s "N/A/deviation needs an
  ADR" requirement for this specific divergence.
- Local dev now defaults to Python 3.13 (`.python-version`), narrowing the gap between "what
  contributors run" and "what the floor requires" without changing the floor itself.
