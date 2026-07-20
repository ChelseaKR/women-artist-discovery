# Claude Code guide — women-artist-discovery

- **Build entrypoint:** [`docs/ROADMAP.md`](./docs/ROADMAP.md) → *Implementation Plan*.
- **Hard guardrails:** the [Guardrails section of the README](./README.md#guardrails)
  is binding — never infer identity from name/voice/image/genre or any heuristic;
  woman includes trans women explicitly (sourced self-identification is the only
  test; no cis/trans distinction exists in the vocabulary); "unknown" is
  first-class and never down-ranked; "female-fronted" is band-composition
  metadata, distinct from any individual's gender; every recommendation shows
  why + identity basis + source; never redistribute a scraped musician-identity
  dataset. `tests/test_no_inference.py` is the enforcement centrepiece — never
  weaken it.
- **Commands:** `make dev` · `make verify` · `make a11y` · `make eval`.
- **Definition of done:** demo recommendations are explainable and reproducible,
  sourced identity is enforced, unknown is retained, and every local gate is
  green. Live username-to-recommendation orchestration is explicitly deferred in
  the roadmap ledger (see `DEFINITION_OF_DONE.md` for the full checklist).
