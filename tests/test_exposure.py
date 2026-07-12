"""FIX-05: computed exposure / rank-fairness metrics + the unknown-retention guarantee.

These are the *generated numbers* behind ``docs/audits/fairness-identity.md``: the
fairness narrative, verified on the recommender's real output rather than only on
the rerank function.
"""

from __future__ import annotations

import pytest
from pipeline.models import (
    Explanation,
    Gender,
    IdentityBasis,
    Recommendation,
    Signal,
)
from recommender.eval import DEFAULT_LENS_SWEEP, fairness_report
from recommender.exposure import (
    FEMALE_FRONTED,
    MAN,
    NONBINARY,
    SEGMENTS,
    UNKNOWN,
    WOMAN,
    FairnessAssertionError,
    assert_unknown_retained,
    exposure_at_k,
    exposure_report,
    identity_segment,
    popularity_identity_crosstab,
    popularity_tier,
    rank_shift_by_segment,
    unknown_retention,
)
from recommender.hybrid import recommend

from .conftest import make_artist

_ALIGNED = frozenset({WOMAN, NONBINARY, FEMALE_FRONTED})


def _recs_by_lens(profile, catalog, source, lenses=DEFAULT_LENS_SWEEP):
    return {
        lens: recommend(profile, catalog, source, k=len(catalog), lens_strength=lens)
        for lens in lenses
    }


def _rec(artist, score, delta=0.0):
    expl = Explanation(
        signals=(Signal("content", "tag", 1.0),),
        identity_basis=IdentityBasis.UNKNOWN
        if artist.identity.gender is Gender.UNKNOWN
        else IdentityBasis.SELF_IDENTIFIED,
        identity_sources=artist.identity.sources,
        summary="why",
    )
    return Recommendation(artist=artist, base_score=score, rerank_delta=delta, explanation=expl)


# -- segmentation (sourced, never inferred) ----------------------------------
def test_identity_segment_reads_sourced_identity_then_composition(catalog) -> None:
    assert identity_segment(catalog["snail-mail"]) == WOMAN
    assert identity_segment(catalog["shamir"]) == NONBINARY
    assert identity_segment(catalog["moses-sumney"]) == MAN
    assert identity_segment(catalog["boygenius"]) == FEMALE_FRONTED  # sourced composition
    assert identity_segment(catalog["mystery-act"]) == UNKNOWN


def test_other_gender_is_its_own_segment_not_unknown() -> None:
    assert identity_segment(make_artist("x", gender=Gender.OTHER)) == "other"


def test_popularity_tier_boundaries() -> None:
    assert popularity_tier(99_999) == "niche"
    assert popularity_tier(100_000) == "mid"
    assert popularity_tier(999_999) == "mid"
    assert popularity_tier(1_000_000) == "popular"


# -- exposure ----------------------------------------------------------------
def test_exposure_shares_sum_to_one(profile, catalog, source) -> None:
    recs = recommend(profile, catalog, source, k=5, lens_strength=0.0)
    shares = exposure_at_k(recs, k=5)
    assert set(shares) == set(SEGMENTS)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_exposure_at_k_empty_is_all_zero() -> None:
    shares = exposure_at_k([], k=5)
    assert set(shares.values()) == {0.0}


def test_lens_shifts_exposure_toward_aligned_segments(profile, catalog, source) -> None:
    at0 = exposure_at_k(recommend(profile, catalog, source, k=5, lens_strength=0.0), k=5)
    at1 = exposure_at_k(recommend(profile, catalog, source, k=5, lens_strength=1.0), k=5)
    aligned0 = sum(at0[s] for s in _ALIGNED)
    aligned1 = sum(at1[s] for s in _ALIGNED)
    assert aligned1 >= aligned0  # the lens surfaces more aligned artists, never fewer


# -- the merge-blocking unknown-retention guarantee --------------------------
def test_unknown_retention_is_100pct_at_every_lens(profile, catalog, source) -> None:
    retention = unknown_retention(_recs_by_lens(profile, catalog, source))
    assert retention  # non-empty sweep
    assert all(value == 1.0 for value in retention.values())


def test_assert_unknown_retained_passes_on_demo_output(profile, catalog, source) -> None:
    assert_unknown_retained(_recs_by_lens(profile, catalog, source))  # must not raise


def test_assert_unknown_retained_detects_a_dropped_unknown() -> None:
    unknown = make_artist("mystery", gender=Gender.UNKNOWN)
    woman = make_artist("w", gender=Gender.WOMAN)
    base = [_rec(unknown, 0.5), _rec(woman, 0.4)]
    boosted = [_rec(woman, 0.4, delta=0.5)]  # unknown vanished from the output
    with pytest.raises(FairnessAssertionError):
        assert_unknown_retained({0.0: base, 1.0: boosted})


def test_assert_unknown_retained_detects_a_penalised_unknown() -> None:
    unknown = make_artist("mystery", gender=Gender.UNKNOWN)
    base = [_rec(unknown, 0.5)]
    penalised = [_rec(unknown, 0.3)]  # score lowered by the (mis-implemented) lens
    with pytest.raises(FairnessAssertionError):
        assert_unknown_retained({0.0: base, 1.0: penalised})


def test_retention_is_one_when_no_unknown_artists_present() -> None:
    woman = make_artist("w", gender=Gender.WOMAN)
    retention = unknown_retention({0.0: [_rec(woman, 0.4)], 1.0: [_rec(woman, 0.4, 0.5)]})
    assert retention == {"0.00": 1.0, "1.00": 1.0}


# -- rank shift (honest re-ordering, no score penalty) -----------------------
def test_rank_shift_moves_aligned_up_without_penalising_unknown(profile, catalog, source) -> None:
    base = recommend(profile, catalog, source, k=len(catalog), lens_strength=0.0)
    boosted = recommend(profile, catalog, source, k=len(catalog), lens_strength=1.0)
    shift = rank_shift_by_segment(base, boosted)
    assert shift[WOMAN] <= 0.0  # sourced women move up (or stay), never down on average
    # And the score guarantee still holds even though positions changed:
    assert_unknown_retained({0.0: base, 1.0: boosted})


# -- cross-tab ---------------------------------------------------------------
def test_crosstab_counts_the_whole_candidate_pool(profile, catalog, source) -> None:
    recs = recommend(profile, catalog, source, k=len(catalog), lens_strength=0.0)
    table = popularity_identity_crosstab(recs)
    total = sum(count for row in table.values() for count in row.values())
    assert total == len(recs)


# -- the full emitted report -------------------------------------------------
def test_exposure_report_has_expected_shape_and_guarantee(profile, catalog, source) -> None:
    report = exposure_report(_recs_by_lens(profile, catalog, source), k=5)
    assert set(report) >= {
        "k",
        "lens_strengths",
        "segments",
        "exposure_at_k",
        "unknown_retention",
        "mean_rank_shift",
        "popularity_identity_crosstab",
        "guarantees",
    }
    guarantees = report["guarantees"]
    assert guarantees["unknown_retention_all_lenses"] is True
    assert guarantees["min_unknown_retention"] == 1.0
    assert guarantees["unknown_downranked_count"] == 0
    # exposure emitted at the required lens strengths (0.0 / 0.5 / 1.0 among them):
    assert {"0.00", "0.50", "1.00"} <= set(report["exposure_at_k"])


def test_fairness_report_from_demo_world_satisfies_the_guarantee(
    demo_user, scrobbles, catalog, source
) -> None:
    report = fairness_report(demo_user, scrobbles, catalog, source, k=5)
    assert report["guarantees"]["unknown_retention_all_lenses"] is True
    # Every lens strength in the sweep is reported with 100% unknown retention.
    assert set(report["unknown_retention"].values()) == {1.0}
