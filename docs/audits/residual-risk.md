# Residual-Risk Register

> Instantiates RESPONSIBLE-TECH-AUDITS §F (security narrative + residual risk).
> **Last verified: 2026-06-30 · Recheck cadence: per dependency / threat-model change.**

## Threat model (STRIDE-lite) of the data flows

`username → Last.fm API → cache → enrichment APIs → resolver → recommender → UI`

| Threat | Vector | Control |
|--------|--------|---------|
| Tampering | cache poisoning via malformed external API data | strict shape validation in all parsers (`pipeline/lastfm.py`, `pipeline/enrich.py`); unrecognised values → unknown, never coerced; `tests/test_adapters.py` |
| Tampering | corrupt cache row asserting an unsourced identity | model invariants re-run on load — fails closed (`tests/test_cache_serde.py::test_corrupt_cache_row_*`) |
| Info disclosure | API key leakage | key from env only; secret scan merge-blocking (`scripts/secret-scan.sh`, CI gitleaks) |
| Info disclosure | listening data exfiltration | local-first; no telemetry; network confined to the API client (`tests/test_privacy.py`) |
| DoS / abuse | hammering upstream APIs | `RateLimiter` + response cache (`pipeline/lastfm.py`, `tests/test_adapters.py`) |
| Elevation / supply chain | vulnerable dependency | `pip-audit` merge-blocking; ruff bandit (`S`) SAST subset |

## Accepted residual risks

| ID | Risk | Why accepted | Owner | Review |
|----|------|--------------|-------|--------|
| RR-1 | **CVE-2025-8869 / GHSA-4xh5-x5gv-qwph** — pip fallback tar extraction | No fixed pip version is published; `pip` is **build-time tooling**, not a shipped runtime dependency. The app never invokes pip at runtime and installs only known PyPI deps. Mitigation: install on Python ≥3.12 (PEP 706 tar filter) where available. Ignored in the audit gate with this justification. | maintainer | per pip release (un-ignore once a fix ships) |
| RR-2 | Upstream identity sources can be **wrong or stale** | Surfaced honestly: confidence is hedged on source conflict; basis + citation + fetch date are shown; corrections fold back via re-enrichment. | maintainer | per source-API change |
| RR-3 | Live performance / load testing **not gated** | This is a local-first, single-user data app with no hosted LLM/API route, so the standard's web/API latency + Lighthouse budgets do not apply. Recorded as a deliberate scope decision. | maintainer | if a hosted multi-user mode is added |
| RR-4 | **Python-3.9-EOL advisory cluster** — 19 advisories across `requests`, `urllib3`, `streamlit`, `pillow` (×6), `pyarrow`, `msgpack`, `filelock` (×2), `pytest`, `pip` (×3) | Python 3.9 reached **EOL 2025-10-31**. Each advisory has a published fix, but **every fix's first fixed release declares `Requires-Python >=3.10`** — so on this repo's declared 3.9 floor **no fix is pip-installable** and forcing the pin breaks `make install`. There is no safe (3.9-installable) bump for any of them. Exposure is bounded: `requests`/`urllib3` are the only core network-path deps (outbound HTTPS to Last.fm/enrichment/Spotify); the rest are `app`-extra streamlit transitives (local-first single-user demo — see RR-3), `dev`-only (`pytest`), or build-time tooling (`pip`, see RR-1). Every ID is justified machine-readably in `docs/audits/vex.json` and waived **byte-identically** in `Makefile` (`AUDIT_IGNORES`) + `.github/workflows/ci.yml`. **Remediation: migrate the project to Python 3.10+ (drops 3.9)** — *flagged but deliberately NOT taken in the dependency-refresh PR*, because it changes `numpy`/`pandas`/`streamlit` resolution and the ruff/mypy target and must be validated on its own (tests, strict typing, a11y, eval). Drop each ID from the waiver the moment the floor moves to ≥3.10 — the fixes are already published there. | maintainer | quarterly + immediately when the Python floor moves to ≥3.10 |

## Enforcement summary

| Commitment | Gate | Where |
|------------|------|-------|
| No high/critical dep vulns (except tracked RR-1 + the RR-4 Python-3.9-EOL cluster, justified in `docs/audits/vex.json`) | auto | `make security` / CI |
| Input validation on external data | auto | `tests/test_adapters.py` |
| Fail-closed on guardrail-violating cache rows | auto | `tests/test_cache_serde.py` |
| Threat-model sign-off | review | this document |
