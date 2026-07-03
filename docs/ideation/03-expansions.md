# Ideation — Expansions (EXP)

> Post-M6 expansion ideas layered on top of the core roadmap (`docs/ROADMAP.md`).
> Tracked separately from the FIX-* remediation backlog so fairness/observability
> features are easy to find. Status is updated as items land.

## EXP-01 — Fairness observability panel — **Done**

**Goal.** A lens-reactive fairness observability panel (table-first) surfacing
exposure share by identity segment and the unknown-retention curve as the lens
slider moves.

**Why.** The re-rank layer's boost-only guarantee (`recommender/rerank.py`) is
proven per-recommendation (`tests/test_unknown_first_class.py`), but there was
no *aggregate* view: which identity segment holds how much of the top-k, and
whether unknown-identity artists are ever displaced out of the results as the
lens strengthens. This closes that observability gap for both the interactive
dashboard and the static a11y-audited render.

**Shipped.**
- `recommender/exposure.py` — pure, UI-agnostic helpers: `identity_segment`,
  `exposure_at_k`, `unknown_retention`, `rank_shift`, `exposure_report`, and
  the display-ready `observability_panel`. Segmentation reuses the sourced
  `IdentityBasis` (self-identified / band-composition / unknown) already
  carried by every `Explanation` — nothing new is inferred.
- `app/dashboard.py` — a "Fairness observability" section (after "Score
  summary") with two `st.table`s (exposure share by segment: base lens vs
  current lens; unknown retention across a fixed lens grid) plus a caption
  tying it to the excellence bar.
- `app/render.py` / `app/build_static.py` — the same panel as an accessible,
  table-first HTML section (`render_cards_html(..., exposure_panel=...)`),
  so the static a11y-audited artifact carries the same guarantee, not just
  the live dashboard. `exposure_panel` defaults to `None` — existing callers
  are unaffected.
- `tests/test_observability.py` — unit tests proving exposure share can
  legitimately differ across the lens while unknown retention stays pinned
  at 1.0 (mirrors the excellence bar); `tests/test_a11y.py` extended to keep
  the a11y gate green with the new section rendered.

**Note.** The verification pass for this item assumed the exposure/segment
data model ("FIX-05") already existed on `main`; it does not yet on this
branch's base commit, so its minimal necessary primitives (`SEGMENTS`,
`identity_segment`, `exposure_at_k`, `exposure_report`) were implemented here
alongside the panel rather than blocking on a separate FIX-05 landing first.
