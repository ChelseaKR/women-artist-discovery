"""The values-aware re-rank — **boost-only**, so unknown is never penalised.

This is where the project's central fairness guarantee is implemented and made
mechanically true: the lens can only *add* a non-negative boost to artists whose
*sourced* identity or *sourced* composition aligns with the lens. It can never
subtract. Therefore:

* an artist with an UNKNOWN identity keeps its exact base score (delta = 0);
* a sourced woman/nonbinary/female-fronted artist may move *up*;
* nothing ever moves *down* because its identity is unknown.

``lens_strength`` ∈ [0, 1] is surfaced in the UI and explained. At 0 the ranking
is identical to the pure hybrid ranking. The maximum boost is bounded so the lens
re-orders without obliterating the underlying taste signal.
"""

from __future__ import annotations

from dataclasses import replace

from pipeline.models import Artist, Recommendation

#: The largest boost the lens can add at full strength, as a fraction of the
#: score scale (base scores are normalised to ~[0, 1]). Bounded so taste still
#: matters; tunable, but never negative.
MAX_BOOST = 0.5


def values_boost_for_artist(artist: Artist, lens_strength: float) -> float:
    """The non-negative boost for an artist. Zero unless *sourced*-aligned."""
    if lens_strength <= 0.0:
        return 0.0
    if not artist.values_aligned:  # unknown or sourced-not-aligned → no boost
        return 0.0
    strength = min(1.0, max(0.0, lens_strength))
    return MAX_BOOST * strength


def values_boost(rec: Recommendation, lens_strength: float) -> float:
    """The non-negative boost for one recommendation. Zero unless sourced-aligned."""
    return values_boost_for_artist(rec.artist, lens_strength)


def sort_and_rank(recs: list[Recommendation]) -> list[Recommendation]:
    """Deterministic ordering: score desc, then artist_id asc; assign 1-based rank."""
    ordered = sorted(recs, key=lambda r: (-r.score, r.artist.artist_id))
    return [rec.with_rank(i + 1) for i, rec in enumerate(ordered)]


def rerank(recs: list[Recommendation], lens_strength: float) -> list[Recommendation]:
    """Apply the boost-only lens and re-sort. Deterministic and non-penalising.

    Raises ``ValueError`` for a lens strength outside [0, 1].
    """
    if not (0.0 <= lens_strength <= 1.0):
        raise ValueError("lens_strength must be in [0, 1]")

    boosted: list[Recommendation] = []
    for rec in recs:
        delta = values_boost(rec, lens_strength)
        assert delta >= 0.0  # invariant: the lens never penalises
        boosted.append(replace(rec, rerank_delta=delta))

    return sort_and_rank(boosted)
