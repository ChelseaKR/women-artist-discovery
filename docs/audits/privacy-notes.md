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
| Playlist export (opt-in) | personal | user-initiated push of the recommended artist names to Spotify | none (sent, not stored) | n/a — only on click |

No special-category data is *inferred*; identity is only ever **sourced** about
public figures (artists), never about the user.

## Outbound data flows

There are exactly two outbound paths, both purpose-limited:

1. **Last.fm / enrichment fetch** — confined to `pipeline/lastfm.py` (asserted by
   `tests/test_privacy.py`), cached locally, rate-limit-respecting.
2. **Playlist export** (`export/`) — the project's only *user-initiated* egress.
   It is opt-in (nothing leaves on load), runs only when the user clicks
   export/connect, and sends just the recommended **artist names** (a public
   search query) to Spotify to build a playlist. The credential-free formats
   (text / CSV / M3U / JSPF) stay fully local. No listening history, no identity
   data, and no telemetry are transmitted. The live HTTP call is isolated in one
   injectable transport (`export/spotify.py::RequestsTransport`); the rest of the
   flow is exercised offline with a fake transport, so the egress surface is a
   single, auditable function.

   *Secrets:* the Spotify app credentials are read from the environment only
   (`WAD_SPOTIFY_CLIENT_ID`, `WAD_SPOTIFY_CLIENT_SECRET`, `WAD_SPOTIFY_REDIRECT_URI`)
   and the OAuth access/refresh tokens are held in memory for the session, never
   written to disk or committed.

## Handling & commitments

- **Local-first.** Everything lives in a single on-disk SQLite file under `data/`
  (git-ignored). Nothing about the user's listening leaves the machine *except*
  when the user explicitly exports a playlist to Spotify, which sends only the
  recommended artist names (see "Outbound data flows" below).
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
| Core network confined to API client | auto | `tests/test_privacy.py` |
| Export egress opt-in & isolated to one transport | auto + review | `tests/test_export.py` (offline fake transport) · this document |
| Lineage timestamps on cache | auto | `tests/test_cache_serde.py` |
| Secrets never in source | auto | secret scan (CI + `make security`) |
| DPIA sign-off | review | this document |
