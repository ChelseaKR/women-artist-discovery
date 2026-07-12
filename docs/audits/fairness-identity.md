# Fairness & Bias — Identity

> Instantiates RESPONSIBLE-TECH-AUDITS §B.
> **Last verified: 2026-07-11 · Recheck cadence: per recommender change.**

## Segments

Artists are segmented by **identity basis** (self-identified / band-composition /
unknown), by **gender** within the self-identified set (woman / man / nonbinary /
other), and by **popularity tier** (listener count).

## Risks & findings

1. **Representational — nonbinary erased / collapsed into a binary.**
   *Finding:* nonbinary is a first-class `Gender` member, resolvable from a sourced
   statement and boosted by the lens exactly like women. Proven end-to-end:
   `tests/test_identity_model.py::test_nonbinary_survives_end_to_end_in_recommendations`
   (a nonbinary artist appears in results with a boost and a correct explanation).

2. **Representational — unknown erased by the re-rank.**
   *Finding:* the lens is **boost-only**; an unknown artist's score is invariant to
   lens strength and it is never dropped. `tests/test_unknown_first_class.py`. This
   is the project's central fairness guarantee. → metric *down-ranked-for-unknown = 0*.

3. **Allocational — the lens over-favours already-popular women.**
   *Mitigation:* the boost is bounded (`MAX_BOOST`, `recommender/rerank.py`) so it
   re-orders without erasing the taste signal, and the base score is taste-only
   (popularity is **not** an input to the hybrid — it is only the eval baseline).
   The demo eval shows the hybrid recovers held-out discoveries that the popularity
   baseline misses (`docs/audits/eval-report.json`).

4. **Men are not penalised.** A sourced man keeps his exact base score under any
   lens strength; he simply receives no boost. `tests/test_rerank.py`,
   `tests/test_unknown_first_class.py::test_man_and_unknown_are_not_penalised_*`.

## Measurement & visibility

Beyond the pass/fail gates above, two **descriptive** instruments report fairness
per run (deliberately not target-driven — they measure, they do not set quotas):

- **Identity-coverage readout** (`recommender/coverage.py`) — "N of K picks carry a
  sourced identity; M surfaced on musical similarity alone." Makes *unknown is
  first-class* legible in the CLI, the dashboard, and the committed static render,
  framing the (common, expected) unknown case as normal, never a gap.
  `tests/test_coverage_readout.py`.
- **Exposure / rank metric** (`recommender/exposure.py`) — top-k exposure share,
  unknown retention, mean rank shift by identity segment, and a popularity-tier
  cross-tab across a lens sweep, reported in `eval-report.json`. It shows what the
  bounded lens changes while separately enforcing that unknown artists are never
  dropped or score-penalised. `tests/test_exposure.py`.

## Enforcement summary

| Commitment | Gate | Where |
|------------|------|-------|
| Nonbinary representable end-to-end | auto | `tests/test_identity_model.py` |
| Unknown retained, never penalised | auto | `tests/test_unknown_first_class.py` |
| Unknown coverage surfaced, not buried | auto | `tests/test_coverage_readout.py` |
| Per-segment exposure reported per run | auto | `tests/test_exposure.py`, `eval-report.json` |
| Bounded, taste-preserving boost | auto | `tests/test_rerank.py` |
| Hybrid beats popularity baseline | auto | `tests/test_eval.py`, `eval-report.json` |
| Representational-harm judgement | review | fairness sign-off on change |
