# Women-Artist Discovery — Implementation Roadmap

> Generic enforcement lives in `/STANDARDS`. This document carries the decisions and project-specific values.
> **Last verified: 2026-05-31 · Recheck cadence: per Last.fm / MusicBrainz / Discogs / Wikidata API change.**

## 1. Snapshot
A hybrid Last.fm-driven music-discovery engine with a values-aware re-ranking layer and a sourced-not-inferred identity model. Python pipeline + Streamlit dashboard; local-first. The technical novelty is doing identity-aware recommendation responsibly — never guessing, always citing, treating unknown as normal.

## 2. Problem & users
- **Problem.** Recommenders are identity-blind by default; there's no good way to discover women/nonbinary/female-fronted artists on purpose without crude gender-guessing.
- **Primary user.** You (single-user, personal); secondarily, anyone who wants values-aware discovery done ethically.
- **Jobs to be done.** "Find new women/nonbinary/female-fronted artists I'll like." · "Don't make the tool guess anyone's gender." · "Tell me *why* each pick showed up."
- **Evidence basis.** Your own scrobble history is the ground truth; offline-evaluate recommendations on held-out listens.

## 3. Product definition
- **Vision.** Discovery that respects both taste and identity, without essentialism.
- **Scope (MoSCoW).**
  - *Must:* Last.fm ingest; enrichment (MusicBrainz/Wikidata/Discogs); hybrid recommender; values-aware re-rank; sourced identity model with unknown-first-class; per-recommendation explanation; dashboard.
  - *Should:* ListenBrainz collaborative signal; playlist/export; ~~thumbs feedback to tune the lens~~ (shipped — see M6 build log addendum below).
  - *Could:* acoustic/content features; a "discovery report"; additional sourced value lenses (e.g., local/indie, BIPOC artists — same sourced approach).
  - *Won't (v1):* inferring identity from any signal; redistributing an identity dataset; cross-user/social features.
- **Non-goals.** Not a gender database product; not identity-blind; not a guessing engine.

## 4. Research & evidence
- **Identity sourcing.** Define the *only* permitted identity sources and their provenance + confidence; document each one's limits (Wikidata P21 is sparse and sometimes wrong; MusicBrainz gender is editorial/self-reported; Discogs gives lineup, not individual identity). Default everywhere is **unknown**.
- **"Female-fronted" definition.** An operational, sourced lineup/role property (who fronts / who's in the band), explicitly *not* a claim about any member's gender.
- **Recommender baseline.** Validate the hybrid against a popularity baseline on held-out scrobbles before adding the re-rank.

## 5. Experience & design
- **Streamlit dashboard.** Enter username → ranked recommendations as "why" cards (signals + identity basis + sources), plus a respectful "unknown — surfaced on similarity" state.
- **Lens control.** A slider for how strongly the values lens re-ranks, always visible and explained.
- **Accessibility.** Keyboard-complete, charts have data-table equivalents, identity/why info never conveyed by color alone. Release gate.

## 6. Architecture
- **Shape.** Python pipeline (ingest → enrich → recommend → re-rank → explain) + SQLite cache + Streamlit UI.
- **Recommender.** Collaborative (Last.fm/ListenBrainz similar-artist signal) + content (tags/genres) hybrid; a re-rank layer applies *sourced* identity weights.
- **Identity resolver.** Pulls only from permitted sources, attaches source + confidence to every label, and defaults to unknown. There is deliberately **no** inference path.
- **Key decisions (ADRs).** Streamlit over React (solo speed, data-app shape; React noted as a later option). Hybrid over single-method (cold-start + serendipity). Identity = sourced-only with unknown-first-class (rejected: name/voice/image/genre inference — unethical and inaccurate). Cache + rate-limit respect (rejected: aggressive scraping).

### Build log (decisions made during implementation, 2026-05-31)
Per the Documentation Standard ("keep docs live"), decisions the plan didn't anticipate:
- **Guardrails as type invariants, not just tests.** `IdentityLabel`/`Source`/`BandComposition` in `pipeline/models.py` raise on any unsourced or mis-sourced identity, so a guardrail violation can't even be constructed. The no-inference test (`tests/test_no_inference.py`) adds an AST scan of the resolver as a regression backstop.
- **`female_fronted` is tri-state** (`True`/`None`), never `False` by inference — absence of a sourced woman/nonbinary front is "unknown", not "male-fronted".
- **Re-rank is boost-only** (`recommender/rerank.py`), which is how "unknown never penalised" is made mechanically true rather than merely intended; bounded by `MAX_BOOST` so taste is preserved.
- **Coverage gate scoped to core logic** (`pipeline` + `recommender`, 94%); the Streamlit UI is verified by the a11y gate + manual walkthrough rather than unit coverage.
- **A11y gate** = static render (`app/render.py` → `docs/audits/dashboard.html`) checked by `pa11y --runner axe`, with a dependency-free `app/a11y_check.py` fallback for offline/CI-without-Chromium.
- **Performance/Lighthouse budgets N/A** for this local-first, single-user data app (no hosted LLM/API route) — recorded as residual risk RR-3.
- **Security:** `pip-audit` + ruff-bandit (`S`) + secret scan are merge-blocking. Accepted, tracked residual risks: RR-1 (CVE-2025-8869, pip tar extraction — build-tooling only) and RR-4 (a 19-advisory cluster whose fixes all require Python ≥3.10, so none is installable on the 3.9 floor — justified per-ID in `docs/audits/vex.json`, waived byte-identically in `Makefile`/`ci.yml`). See `docs/audits/residual-risk.md`.
- **Runtime:** Python 3.9 (`mypy --strict`); deps: `requests`, `numpy` (runtime), `streamlit`/`pandas` (app extra). **Flagged next step (RR-4 remediation):** migrate the floor to **Python 3.10+** (3.9 went EOL 2025-10-31) — unblocks the published security fixes for `requests`/`urllib3`/`streamlit`/`pillow`/`pyarrow`/`msgpack`/`filelock`/`pytest`/`pip`, but is a standalone change (re-resolves numpy/pandas/streamlit + moves the ruff/mypy target) to validate on its own, so it is intentionally **out of scope for the dependency-refresh PR**.

### Build log addendum (2026-06-29) — playlist export + "Why this artist"
- **"Why this artist" centralised** in `recommender/why.py` (`WhyThisArtist`): one render-agnostic explanation — sourced identity statement, hybrid + values-lens reasons, and provenance that shows *the raw value each source asserted* (not just a label), plus an explicit `inferred = False`. The dashboard, the a11y static renderer (`app/render.py`), the CLI, and the export now share this single source of truth, removing the previously-duplicated identity wording (also reused by `recommender/explain.py`).
- **Playlist export** as a new top-level `export/` package — deliberately *outside* `pipeline`/`recommender` so the privacy test's "core network confined to `lastfm.py`" guarantee still holds and the export egress is a separate, opt-in boundary. Credential-free fallbacks (plain text / CSV / M3U / JSPF, `export/tracklist.py`) need no account; live Spotify (`export/spotify.py`) uses the Authorization Code OAuth flow with an injectable `HttpTransport` (fake in tests, `requests` only in `RequestsTransport`), credentials from env only. `wad export` CLI + dashboard download buttons + a Spotify connect panel. New egress documented in `docs/audits/privacy-notes.md`.
- **No new dependencies** (stdlib `base64`/`csv`/`json`/`secrets`/`urllib`; `requests` already present). Realised the roadmap "Should: playlist/export" item.
- **Needs real creds to run live:** a Spotify app + a browser OAuth consent; only `RequestsTransport` is uncovered (live network), exactly like `LastfmClient`.

### Build log addendum (2026-07-02) — M6 feedback loop (thumbs feedback to tune the lens)
- **Shipped** the roadmap "Should: thumbs feedback to tune the lens" item. `recommender/feedback.py` adds a `Feedback` dataclass (`username`, `artist_id`, `vote ∈ {+1,-1}`, `ts`) and a pure `feedback_adjustment(artist, feedbacks, strength) -> float`: votes for one artist are summed and squashed through `tanh`, then scaled by `MAX_FEEDBACK` (0.3) — bounded within `[-MAX_FEEDBACK, MAX_FEEDBACK]`, mirroring `rerank.MAX_BOOST`'s bound but signed, since feedback (unlike the values lens) is allowed to lower an artist.
- **Kept artist-scoped, by construction, to preserve the fairness guarantee.** `feedback_adjustment` only folds in votes whose `artist_id` matches the artist being scored — a thumbs-down on one artist can never lower any other artist, let alone a whole identity class. Identity never appears in `recommender/feedback.py` at all. `tests/test_unknown_first_class.py::test_feedback_does_not_reintroduce_an_identity_penalty` asserts this end-to-end through `recommend()`, alongside the lens's own boost-only contract and the unknown-first-class guarantee, all three holding simultaneously with feedback in the mix.
- **Composed into `base_score`, not `rerank_delta`.** `recommender/hybrid.recommend()` gained optional `feedbacks`/`feedback_strength` params; the adjustment is added to each candidate's base (taste) score *before* the values lens is applied and the list is re-sorted, so `rerank_delta` stays boost-only and non-negative (its own tested invariant) while feedback can move a score either direction.
- **Persisted locally**, matching the cache's existing local-first, sourced-lineage posture: `pipeline/cache.py` adds a `feedback` table (`UNIQUE(username, artist_id)`, `ts` + `fetched_at` lineage), a `record_feedback()`/`load_feedback()` pair, and a schema-versioning migration runner (`CACHE_SCHEMA_VERSION` 1 → 2, `PRAGMA user_version`-backed, forward-only) so an older cache file migrates in place and a newer one fails loudly rather than being misread.
- **CLI:** `wad feedback --artist <id> --up/--down [--user <username>]` records a vote; `wad recommend` / `wad export` now load the demo user's stored feedback and pass it into `recommend()`. Verified live: a thumbs-down on `snail-mail` demoted it from rank 1 to rank 2 behind `boygenius` in the `--lens 0.5` demo ranking, with every other artist's score unchanged.
- **No new dependencies** (stdlib `math.tanh`, `sqlite3` already present).

## 7. Quality attributes & metrics
| Metric | Target | Measured by | Gate |
|--------|--------|-------------|------|
| Inferred identity labels (name/voice/image/genre) | 0 | labeling-pipeline test (asserts no inference path exists) | merge-blocking |
| Identity labels carrying a cited source | 100% | provenance test | merge-blocking |
| Recommendations down-ranked solely for unknown identity | 0 | re-rank test | merge-blocking |
| "Why recommended" present | 100% of recs | explanation test | merge-blocking |
| Recommendation reproducibility (seeded) | deterministic | snapshot test | merge-blocking |
| axe violations (dashboard) | 0 | pa11y-ci | merge-blocking |
| External API rate-limit compliance | within limits, cached | integration test | merge-blocking |
| Coverage | ≥ 85% / ≥ 80% | coverage | merge-blocking |

**Testing.** Unit (identity resolver refuses inference; re-rank math; unknown handling), integration (Last.fm/MusicBrainz/Discogs/Wikidata adapters with cached fixtures), eval (offline recommender quality vs popularity baseline), a11y.

## 8. Implementation plan for Claude Code
```
pipeline/     (ingest, enrich, identity resolver)
recommender/  (collaborative, content, hybrid, re-rank, explain)
app/          (streamlit dashboard)
data/         (sqlite cache)
docs/
```
- **M0 — Scaffold & gates.** Repo + CI (`/STANDARDS` gates + axe + the no-inference test). *Done when `make verify` is green and the no-inference test exists and passes.*
- **M1 — Ingest + cache.** Last.fm scrobbles/tags into the cache. *Done when a username yields a stored listening profile.*
- **M2 — Identity resolver.** Permitted-source resolver with provenance + unknown default; the guardrail tests. *Done when labels carry sources and inference paths are provably absent.*
- **M3 — Recommender.** Collaborative + content hybrid. *Done when held-out eval beats a popularity baseline.*
- **M4 — Values-aware re-rank.** Sourced identity weighting; unknown never penalized. *Done when re-rank tests pass and unknown artists still surface.*
- **M5 — Dashboard + explanations.** Streamlit UI with why-cards + sources; a11y. *Done when every rec shows why + basis + source and axe = 0.*
- **M6 — Polish.** Feedback loop (shipped — thumbs feedback to tune the lens, see build log addendum 2026-07-02), export (shipped), discovery report. *Done when all §7 gates pass.*
- **Claude Code approach.** Write the no-inference guardrail test *first*; identity defaults to unknown everywhere; never let a missing label change a score.

## 9. Go-to-market & community
- **Positioning.** "Discovery with a values lens, done right." A thoughtful portfolio piece on responsible, identity-aware ML.
- **Marketing/comms.** The writeup is the artifact: how to do values-aware recommendation *without* inferring identity. That's a rare, credible engineering-ethics story.
- **Community.** Contribution guide; a reusable "identity data ethics" doc; a correction mechanism for mislabeled sources.

## 10. Legal & compliance
- **API terms** (Last.fm, Discogs, MusicBrainz, Wikidata) honored; **no redistribution** of a scraped identity dataset; personal-use scope; MusicBrainz/Wikidata attribution.
- **Privacy.** Listening data is personal → local-first; no third-party analytics.

## 11. Operations & sustainability
- **Hosting/cost.** Runs locally or on a small host; cheap; the cache cuts API load.
- **Maintenance.** Periodic re-enrichment; source corrections folded back in.
- **Sustainability.** Single-user, low cost, open methodology survives the maintainer.

## 12. Responsible-tech summary
Top risks: (1) misgendering/essentialism via inference → sourced-only + unknown-first-class + a real nonbinary model; (2) building a misusable musician-identity database → minimize, cite, correctable, no redistribution; (3) listening-data privacy → local-first; (4) a re-rank that quietly erases unknown artists → unknown never penalized (tested). Full treatment in [`RESPONSIBLE-TECH-AUDITS.md`](./RESPONSIBLE-TECH-AUDITS.md).
