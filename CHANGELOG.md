# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/); this project
intends to adhere to [Semantic Versioning](https://semver.org/) once a first version is tagged.

**Release stance:** this is unreleased pre-1.0 development software — see `SECURITY.md` and
`CITATION.cff`. There is no tagged release yet, so everything below lives under `[Unreleased]`.
When `v0.1.0` is tagged, its entries move to a new `## [0.1.0] - YYYY-MM-DD` section dated to the
tag, not backfilled to an earlier commit date.

## [Unreleased]

### Added
- Playlist export: push recommendations to a Spotify playlist (OAuth Authorization Code flow,
  env-only credentials) or download a portable, account-free track list (plain text / CSV / M3U /
  JSPF) (#1).
- Shared `WhyThisArtist` explanation object, reused by the dashboard, static a11y render, CLI, and
  export, so identity/why wording cannot drift between surfaces (#1).
- `CITATION.cff` (#4).
- `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (#7).
- i18n `N/A` declaration (`docs/I18N.md`) plus a merge-blocking enforcement gate
  (`scripts/i18n-gate.sh`, CI `i18n` stage) (#8).
- Renovate (`renovate.json`) with `minimumReleaseAge: 72 hours` and GitHub Actions digest pinning
  (BL-8, 56628ee).

### Changed
- Migrated the Python floor from 3.9 to `>=3.10` (#6). Unblocked every dependency fix gated to
  Python ≥3.10 (see Security, below) and dropped Python 3.9 (EOL 2025-10-31) from the CI matrix.

### Security
- `persist-credentials: false` on the CI checkout step, so the default `GITHUB_TOKEN` is not
  persisted for later steps (#4).
- All GitHub Actions `uses:` pinned to 40-character commit SHAs with version comments, closing the
  prior floating-tag supply-chain gap (#4, kept current by Renovate's digest pinning).
- Dependency security refresh: documented and waived the 19-advisory Python-3.9-EOL cluster
  (`requests`, `urllib3`, `streamlit`, `pillow`, `pyarrow`, `msgpack`, `filelock`, `pytest`, `pip`)
  with a committed, justified VEX (#5), then **resolved it outright** via the Python 3.10+
  migration (#6) — `pip-audit` now runs with an **empty** waiver list and no `--ignore-vuln` flags.
  See `docs/audits/residual-risk.md` (RR-1, RR-4) and `docs/audits/vex.json`.

---

*Older history predating 2026-06-29 is not available — the git history backing this repository was
reset on that date (see `docs/ROADMAP.md` and the audit trail in `audit-2026-07-05/` for context);
this changelog starts from the current history's initial commit forward.*
