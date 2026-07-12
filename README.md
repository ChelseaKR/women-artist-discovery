# Women-Artist Discovery

**A music-discovery engine that reads your Last.fm history and surfaces new women, nonbinary, and female-fronted artists you'd actually like** — with an explicit values lens, because mainstream recommenders are identity-blind by default. A hybrid recommender (collaborative + content) with a values-aware re-ranking layer, and one hard rule running underneath all of it: identity is never inferred, only sourced from self-identification, and "unknown" is a normal, first-class answer.

**Status:** `Beta` · **Track:** Personal (data/ML + small web app) · **License:** MIT · **Data:** personal/local

> **Build:** M0–M6 implemented. `make verify` runs the gate set that actually exists and is
> merge-blocking today: `ruff format --check` + `ruff check` (incl. a bandit `S` SAST subset),
> `mypy --strict`, 168 tests @ 94% coverage, `pip-audit` (empty waiver list) + a secret scan, the
> axe accessibility gate (0 violations), the offline eval gate (hybrid beats the popularity
> baseline), and an i18n `N/A`-declaration gate. **Not yet wired:** CodeQL, zizmor, OpenSSF
> Scorecard, a lockfile-drift check, and CHANGELOG-lint — see the Standards Conformance table below
> and `audit-2026-07-05/women-artist-discovery-REMEDIATION.md` for status. Review-gated sign-offs
> (manual screen-reader + keyboard walkthrough) are pending the first release — see
> [`docs/audits/`](./docs/audits/). Quickstart: `make install && make dev` (demo mode, no API key)
> · `make verify`.

## Why it matters
Your library leans toward women and female-fronted bands by taste, but no recommender helps you lean into that on purpose without either ignoring identity entirely or guessing it crudely. Doing this *well* — sourced, transparent, non-essentialist — is the whole point and the interesting part.

## What it does
- **Pulls your listening** (scrobbles + tags) from Last.fm; enriches with MusicBrainz/ListenBrainz, Wikidata, and Discogs.
- **Hybrid recommendations:** collaborative similarity + content/tags, then a values-aware re-rank.
- **Sourced identity, never inferred:** identity basis is shown and cited; nonbinary is represented properly; unknown artists are surfaced on musical merit alone.
- **Explains every pick:** a shared "Why this artist" view — why (which signals) + identity basis + provenance (the *raw value each source asserted*, never inferred).
- **Export your picks:** push the current set to a Spotify playlist (env-configured OAuth), or download a portable, account-free track list (plain text / CSV / M3U / JSPF).
- **Local-first:** your listening history stays yours; the only opt-in egress is a user-initiated playlist export (artist names only).

## For Claude Code
- **Build entrypoint:** [`docs/ROADMAP.md`](./docs/ROADMAP.md) → *Implementation Plan*.
- **Hard guardrails:** **never infer an artist's gender or identity from name, voice, image, genre, or any heuristic** — identity labels come only from cited self-identification sources (artist statement, sourced Wikidata P21 claim, MusicBrainz gender field) and must carry that citation; **"unknown" is first-class and must never reduce, down-rank, or drop a recommendation**; "female-fronted" is band-composition metadata (lineup/role), sourced not guessed, and kept distinct from any individual's gender; every recommendation must show why + identity basis + source; do not redistribute a scraped musician-identity dataset (minimize, cite, keep correctable).
- **Commands:** `make dev` · `make verify` · `make a11y` · `make eval`.
- **Definition of done:** from your Last.fm username, the app returns explainable recommendations weighted toward women/nonbinary/female-fronted artists, with sourced (never inferred) identity bases and unknown handled gracefully — every gate in `make verify` green (see the Standards Conformance table below for what is and isn't wired yet).

## Observability
**Tier C** — OTel tracing is out-of-scope (no network/server surface); the only planned surface is
an opt-in `--log-format json` flag. *(That flag is not implemented yet — the CLI does no logging
today, `grep -r "import logging"` = 0 hits — so this declares the Tier C ceiling this repo commits
to, not current behavior. Tracked as a P3 follow-up in the remediation plan.)*

## AI-evaluation status
In scope per `AI-EVALUATION-STANDARD.md` §0 as a classical-ML recommender (no LLM, no RAG, no
generation, no judge — verified: the only third-party deps are `requests`/`numpy`/`streamlit`/
`pandas`). §1–3's LLM/RAG/judge gates are dormant. The gate that **is** active and merge-blocking:
the offline eval must beat the popularity baseline (`make eval`, `docs/audits/eval-report.json`).
The first LLM SDK import anywhere in this repo flips this status to `APPLIES` in full and activates
§1–3. See `docs/RESPONSIBLE-TECH-AUDITS.md` for the full AI-governance picture.

## Standards
Inherits [`/STANDARDS`](../STANDARDS/). Per-standard declarations (Documentation Standard's
"a repo must declare Applies/N/A for every standard, not just inherit silently" rule):

| # | Standard | Status | Notes |
|---|----------|--------|-------|
| 1 | Quality & Metrics | Applies | Gaps tracked in `audit-2026-07-05/`; ROADMAP §7 metrics ledger |
| 2 | Code Quality | Applies | Gaps (tool-floor drift, complexity gate, PEP 735 groups) tracked in `audit-2026-07-05/` |
| 3 | Security & Supply-Chain | Applies — **ASVS 5.0 Level 1** | No auth / no multi-user surface, so L2 controls are N/A (no server); see `docs/RESPONSIBLE-TECH-AUDITS.md` §F |
| 4 | CI/CD | Applies | CODEOWNERS + a proposed branch ruleset are committed; the ruleset is **not yet applied live** — see `docs/audits/branch-ruleset.json` |
| 5 | Release & Versioning | Applies — **release-producing, unreleased** | No tag/release exists yet; see `CHANGELOG.md` and `SECURITY.md` for the current stance |
| 6 | Accessibility | Applies | axe gate blocking (0 violations); manual screen-reader + keyboard sign-offs pending the first release (`docs/audits/accessibility-2026-05-31.md`) |
| 7 | Observability | Applies — **Tier C** | See Observability section above |
| 8 | Internationalization | **N/A** | Single-user, operator-only output — `docs/I18N.md` (self-enforced via `scripts/i18n-gate.sh`) |
| 9 | AI Evaluation | Applies — **narrow** | See AI-evaluation status above |
| 10 | Documentation | Applies | Gaps (ADR log, CHANGELOG-lint, staleness gate) tracked in `audit-2026-07-05/` |
| 11 | Responsible-Tech Framework | Applies | Audits A–F committed — `docs/RESPONSIBLE-TECH-AUDITS.md` |

Open gaps for every row above are tracked in the dated conformance audit
(`audit-2026-07-05/women-artist-discovery-AUDIT.md`) and its remediation plan
(`audit-2026-07-05/women-artist-discovery-REMEDIATION.md`) rather than individual GitHub issues at
this time.
