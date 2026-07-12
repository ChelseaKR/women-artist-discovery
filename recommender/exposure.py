"""Computed exposure & rank-fairness metrics for the values lens (FIX-05).

Turns the fairness *narrative* (``docs/audits/fairness-identity.md``) into
*generated numbers* committed to ``docs/audits/eval-report.json``. Nothing here
infers gender: every segment is read from an artist's **sourced** identity (or
sourced band composition). The residual ``unknown`` segment is first-class and is
the subject of the merge-blocking retention guarantee below.

Metric choices (short justification, per FIX-05's requirement):

* **Exposure@k** — the *count-based* share of the top-``k`` recommendation slots a
  segment occupies. It is the simplest, most legible allocation measure; we report
  it per lens strength so the lens's re-allocation is visible. (Attention-weighted
  exposure — discounting lower ranks — is a defensible alternative; we prefer the
  unweighted share because the list is short and every surfaced slot is seen.)
* **Unknown-retention** — the fraction of ``unknown``-identity artists whose score
  *and* presence in the output are preserved as the lens strengthens. It is 1.0 by
  construction (the lens is boost-only) and is *verified on the emitted output*,
  not only on the rerank function — see :func:`assert_unknown_retained`. This is
  "down-ranked-for-unknown = 0" expressed as a number over real output.
* **Rank-shift** — the mean change in list position per segment relative to pure
  taste (lens 0). It is honest about the lens's *re-ordering*: aligned artists move
  up (negative shift), and an unknown artist may move down *in position* — but never
  in **score** (its score is invariant; retention stays 1.0). A position change
  caused by a genuinely-aligned artist rising is the lens working, not a penalty.
* **Popularity-tier x identity** — cross-tabs the candidate pool by listener count
  (:attr:`~pipeline.models.Artist.listeners`), surfacing the "lens over-favours
  already-popular women" allocational risk named in ``fairness-identity.md`` §3.
"""

from __future__ import annotations

from pipeline.models import Artist, Gender, Recommendation

#: Identity segments (sourced-only; ``unknown`` is first-class and never inferred).
WOMAN = "woman"
NONBINARY = "nonbinary"
FEMALE_FRONTED = "female-fronted"
MAN = "man"
OTHER = "other"
UNKNOWN = "unknown"

#: Emitted in a fixed order for a stable, diffable report.
SEGMENTS: tuple[str, ...] = (WOMAN, NONBINARY, FEMALE_FRONTED, MAN, OTHER, UNKNOWN)

#: Popularity tiers by listener count (the allocational-risk cross-tab axis).
TIERS: tuple[str, ...] = ("niche", "mid", "popular")
_NICHE_CEILING = 100_000
_MID_CEILING = 1_000_000


class FairnessAssertionError(AssertionError):
    """Raised when the emitted output violates the unknown-retention guarantee."""


def identity_segment(artist: Artist) -> str:
    """Segment an artist by *sourced* identity, then sourced composition, else unknown.

    Individual sourced gender wins; a band whose *sourced* composition is
    female-fronted (but whose own gender is unknown) is ``female-fronted``; anything
    left is first-class ``unknown``. No inference is ever performed here.
    """
    gender = artist.identity.gender
    if gender is Gender.WOMAN:
        return WOMAN
    if gender is Gender.NONBINARY:
        return NONBINARY
    if gender is Gender.MAN:
        return MAN
    if gender is Gender.OTHER:
        return OTHER
    if artist.female_fronted is True:  # sourced band composition, not a personal claim
        return FEMALE_FRONTED
    return UNKNOWN


def popularity_tier(listeners: int) -> str:
    """Bucket a listener count into a coarse popularity tier."""
    if listeners < _NICHE_CEILING:
        return "niche"
    if listeners < _MID_CEILING:
        return "mid"
    return "popular"


def _lens_key(lens_strength: float) -> str:
    """Stable string key for a lens strength (JSON object keys must be strings)."""
    return f"{lens_strength:.2f}"


def exposure_at_k(recs: list[Recommendation], k: int) -> dict[str, float]:
    """Share of the top-``k`` recommendation slots held by each identity segment."""
    top = recs[:k]
    counts = dict.fromkeys(SEGMENTS, 0)
    for rec in top:
        counts[identity_segment(rec.artist)] += 1
    n = len(top)
    return {seg: round(counts[seg] / n, 4) if n else 0.0 for seg in SEGMENTS}


def _unknown_scores(recs: list[Recommendation]) -> dict[str, float]:
    """artist_id -> score for every ``unknown``-segment artist in the output."""
    return {r.artist.artist_id: r.score for r in recs if identity_segment(r.artist) == UNKNOWN}


def unknown_retention(
    recs_by_lens: dict[float, list[Recommendation]], *, base_lens: float = 0.0
) -> dict[str, float]:
    """Per-lens fraction of pure-taste unknown artists retained with an unchanged score.

    Computed over the *full emitted output* at each lens (presence + score), not on
    the rerank function. 1.0 means every unknown artist that pure taste surfaced is
    still present and un-penalised at that lens strength.
    """
    base = _unknown_scores(recs_by_lens[base_lens])
    out: dict[str, float] = {}
    for lens in sorted(recs_by_lens):
        present = _unknown_scores(recs_by_lens[lens])
        if not base:
            out[_lens_key(lens)] = 1.0
            continue
        retained = sum(1 for aid, sc in base.items() if present.get(aid) == sc)
        out[_lens_key(lens)] = round(retained / len(base), 4)
    return out


def _unknown_downranked_count(
    recs_by_lens: dict[float, list[Recommendation]], *, base_lens: float = 0.0
) -> int:
    """Number of (unknown-artist, lens) pairs where the lens dropped it or cut its score."""
    base = _unknown_scores(recs_by_lens[base_lens])
    count = 0
    for lens, recs in recs_by_lens.items():
        if lens == base_lens:
            continue
        present = _unknown_scores(recs)
        for aid, base_score in base.items():
            if aid not in present or present[aid] < base_score:
                count += 1
    return count


def assert_unknown_retained(
    recs_by_lens: dict[float, list[Recommendation]], *, base_lens: float = 0.0
) -> None:
    """Merge-blocking guarantee, checked on emitted output: unknown is never penalised.

    Raises :class:`FairnessAssertionError` if, at any lens strength, an
    ``unknown``-identity artist surfaced by pure taste is dropped from the output or
    has its score lowered. Boost-only reranking makes this hold by construction; this
    verifies it on the *numbers the eval actually emits*.
    """
    base = _unknown_scores(recs_by_lens[base_lens])
    for lens in sorted(recs_by_lens):
        present = _unknown_scores(recs_by_lens[lens])
        for aid, base_score in base.items():
            if aid not in present:
                raise FairnessAssertionError(
                    f"unknown artist {aid!r} dropped from output at lens {lens}"
                )
            if present[aid] < base_score:
                raise FairnessAssertionError(
                    f"unknown artist {aid!r} was down-ranked by the lens at {lens}: "
                    f"score {base_score} -> {present[aid]}"
                )


def rank_shift_by_segment(
    base_recs: list[Recommendation], lens_recs: list[Recommendation]
) -> dict[str, float]:
    """Mean change in list position per segment, ``lens`` vs pure taste (negative = up)."""
    base_rank = {r.artist.artist_id: i for i, r in enumerate(base_recs, start=1)}
    shifts: dict[str, list[int]] = {seg: [] for seg in SEGMENTS}
    for i, rec in enumerate(lens_recs, start=1):
        aid = rec.artist.artist_id
        if aid in base_rank:
            shifts[identity_segment(rec.artist)].append(i - base_rank[aid])
    return {seg: round(sum(v) / len(v), 4) if v else 0.0 for seg, v in shifts.items()}


def popularity_identity_crosstab(recs: list[Recommendation]) -> dict[str, dict[str, int]]:
    """Cross-tab the candidate pool: popularity tier x identity segment (counts)."""
    table: dict[str, dict[str, int]] = {tier: dict.fromkeys(SEGMENTS, 0) for tier in TIERS}
    for rec in recs:
        table[popularity_tier(rec.artist.listeners)][identity_segment(rec.artist)] += 1
    return table


def exposure_report(
    recs_by_lens: dict[float, list[Recommendation]], *, k: int, base_lens: float = 0.0
) -> dict[str, object]:
    """Assemble the JSON-able fairness block emitted into ``eval-report.json``.

    ``recs_by_lens`` maps a lens strength to the *full* ranked output at that lens.
    The ``guarantees`` sub-block carries the merge-blocking signal the CLI checks.
    """
    lenses = sorted(recs_by_lens)
    retention = unknown_retention(recs_by_lens, base_lens=base_lens)
    downranked = _unknown_downranked_count(recs_by_lens, base_lens=base_lens)
    min_retention = min(retention.values()) if retention else 1.0
    return {
        "k": k,
        "lens_strengths": lenses,
        "segments": list(SEGMENTS),
        "exposure_at_k": {_lens_key(s): exposure_at_k(recs_by_lens[s], k) for s in lenses},
        "unknown_retention": retention,
        "mean_rank_shift": {
            _lens_key(s): rank_shift_by_segment(recs_by_lens[base_lens], recs_by_lens[s])
            for s in lenses
            if s != base_lens
        },
        "popularity_identity_crosstab": popularity_identity_crosstab(recs_by_lens[base_lens]),
        "guarantees": {
            "unknown_retention_all_lenses": min_retention >= 1.0 and downranked == 0,
            "min_unknown_retention": min_retention,
            "unknown_downranked_count": downranked,
        },
    }
