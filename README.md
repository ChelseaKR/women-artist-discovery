# Women-Artist Discovery

**A music-discovery engine that reads your Last.fm history and surfaces new women, nonbinary, and female-fronted artists you'd actually like** — with an explicit values lens, because mainstream recommenders are identity-blind by default. A hybrid recommender (collaborative + content) with a values-aware re-ranking layer, and one hard rule running underneath all of it: identity is never inferred, only sourced from self-identification, and "unknown" is a normal, first-class answer.

**Status:** `Beta` · **Track:** Personal (data/ML + small web app) · **License:** MIT · **Data:** personal/local

> **Build:** M0–M6 implemented; all *checkable* `/STANDARDS` gates green via `make verify` (lint, `mypy --strict`, 108 tests @ 94% coverage, dep-audit, secret scan, a11y = 0 violations, eval beats the popularity baseline). Review-gated sign-offs (manual screen-reader walkthrough) pending first release — see [`docs/audits/`](./docs/audits/). Quickstart: `make install && make dev` (demo mode, no API key) · `make verify`.

## Why it matters
Your library leans toward women and female-fronted bands by taste, but no recommender helps you lean into that on purpose without either ignoring identity entirely or guessing it crudely. Doing this *well* — sourced, transparent, non-essentialist — is the whole point and the interesting part.

## What it does
- **Pulls your listening** (scrobbles + tags) from Last.fm; enriches with MusicBrainz/ListenBrainz, Wikidata, and Discogs.
- **Hybrid recommendations:** collaborative similarity + content/tags, then a values-aware re-rank.
- **Sourced identity, never inferred:** identity basis is shown and cited; nonbinary is represented properly; unknown artists are surfaced on musical merit alone.
- **Explains every pick:** why (which signals) + identity basis + sources.
- **Local-first:** your listening history stays yours.

## For Claude Code
- **Build entrypoint:** [`docs/ROADMAP.md`](./docs/ROADMAP.md) → *Implementation Plan*.
- **Hard guardrails:** **never infer an artist's gender or identity from name, voice, image, genre, or any heuristic** — identity labels come only from cited self-identification sources (artist statement, sourced Wikidata P21 claim, MusicBrainz gender field) and must carry that citation; **"unknown" is first-class and must never reduce, down-rank, or drop a recommendation**; "female-fronted" is band-composition metadata (lineup/role), sourced not guessed, and kept distinct from any individual's gender; every recommendation must show why + identity basis + source; do not redistribute a scraped musician-identity dataset (minimize, cite, keep correctable).
- **Commands:** `make dev` · `make verify` · `make a11y` · `make eval`.
- **Definition of done:** from your Last.fm username, the app returns explainable recommendations weighted toward women/nonbinary/female-fronted artists, with sourced (never inferred) identity bases and unknown handled gracefully — all `/STANDARDS` gates green.

## Standards
Inherits [`/STANDARDS`](../STANDARDS/).
