# Privacy Notes (DPIA-style)

> Instantiates RESPONSIBLE-TECH-AUDITS §C.
> **Last verified: 2026-05-31 · Recheck cadence: per data-flow change.**

## Data inventory

| Data | Sensitivity | Justification | Storage | Retention |
|------|-------------|---------------|---------|-----------|
| Last.fm username | low (personal) | identifies whose history to fetch | in-memory / local cache | until cache cleared |
| Scrobbles (plays) | personal | the recommendation ground truth | `data/cache.db` (local) | until `make clean` |
| Enriched artist metadata | public | identity + tags + similarity | `data/cache.db` (local) | re-enriched on demand |
| API responses | public | rate-limit-respecting cache | `data/cache.db` (local) | overwritten on refetch |

No special-category data is *inferred*; identity is only ever **sourced** about
public figures (artists), never about the user.

## Handling & commitments

- **Local-first.** Everything lives in a single on-disk SQLite file under `data/`
  (git-ignored). Nothing about the user's listening leaves the machine.
- **No telemetry / no third-party analytics.** Enforced by source scan:
  `tests/test_privacy.py` asserts no analytics SDK is imported and that network
  egress exists **only** in the Last.fm API client (`pipeline/lastfm.py`); the
  cache uses stdlib `sqlite3` only.
- **Data minimisation & lineage.** Only what's needed is stored, each row with a
  `fetched_at` timestamp (`pipeline/cache.py`, `tests/test_cache_serde.py`).
- **Deletion path.** `make clean` removes the local cache (`data/*.db`); there is
  no remote copy to chase.
- **Secrets.** Any API key is read from the environment (`WAD_LASTFM_API_KEY`),
  never committed; secret scan is merge-blocking (`scripts/secret-scan.sh`, CI
  gitleaks).

## Enforcement summary

| Commitment | Gate | Where |
|------------|------|-------|
| No telemetry / analytics | auto | `tests/test_privacy.py` |
| Network confined to API client | auto | `tests/test_privacy.py` |
| Lineage timestamps on cache | auto | `tests/test_cache_serde.py` |
| Secrets never in source | auto | secret scan (CI + `make security`) |
| DPIA sign-off | review | this document |
