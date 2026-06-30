"""Metric: recommendation reproducibility (seeded) = deterministic (snapshot)."""

from __future__ import annotations

from recommender.hybrid import recommend


def _signature(recs):
    return [(r.rank, r.artist.artist_id, round(r.score, 6)) for r in recs]


def test_recommend_is_deterministic_across_runs(profile, catalog, source) -> None:
    a = _signature(recommend(profile, catalog, source, k=10, lens_strength=0.5))
    b = _signature(recommend(profile, catalog, source, k=10, lens_strength=0.5))
    assert a == b


def test_recommend_matches_expected_snapshot(profile, catalog, source) -> None:
    """A frozen snapshot of the pure-taste ranking — changes must be intentional."""
    # demo_profile already "knows" lucy-dacus / soccer-mommy / adrianne-lenker
    # (they appear in the later listening window), so they are correctly excluded.
    got = [r.artist.artist_id for r in recommend(profile, catalog, source, k=6, lens_strength=0.0)]
    assert got == [
        "snail-mail",
        "mystery-act",  # unknown identity, surfaced purely on similarity
        "boygenius",
        "shamir",
        "moses-sumney",
        "arena-men",
    ]


def test_tie_break_is_stable_by_artist_id() -> None:
    from pipeline.models import Explanation, IdentityBasis, Recommendation, Signal
    from recommender.rerank import sort_and_rank

    from .conftest import make_artist

    def rec(aid):
        return Recommendation(
            artist=make_artist(aid),
            base_score=0.5,  # identical scores → id breaks the tie
            rerank_delta=0.0,
            explanation=Explanation(
                signals=(Signal("content", "d", 1.0),),
                identity_basis=IdentityBasis.UNKNOWN,
                identity_sources=(),
                summary="why",
            ),
        )

    out = sort_and_rank([rec("zebra"), rec("apple"), rec("mango")])
    assert [r.artist.artist_id for r in out] == ["apple", "mango", "zebra"]
