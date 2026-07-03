"""Unknown-retention checked on emitted output, not just on rerank's math (EXP-10)."""

from __future__ import annotations

import pytest
from pipeline.models import (
    BandComposition,
    Explanation,
    FrontPerson,
    Gender,
    IdentityBasis,
    IdentityLabel,
    Recommendation,
    Signal,
    Source,
    SourceKind,
)
from recommender.exposure import (
    FEMALE_FRONTED,
    MAN,
    NONBINARY,
    SEGMENTS,
    UNKNOWN,
    WOMAN,
    FairnessAssertionError,
    assert_unknown_retained,
    identity_segment,
    unknown_retention,
)
from recommender.rerank import rerank

from .conftest import make_artist


def _rec(artist, base):
    return Recommendation(
        artist=artist,
        base_score=base,
        rerank_delta=0.0,
        explanation=Explanation(
            signals=(Signal("content", "d", 1.0),),
            identity_basis=IdentityBasis.SELF_IDENTIFIED
            if artist.identity.is_known
            else IdentityBasis.UNKNOWN,
            identity_sources=artist.identity.sources,
            summary="why",
        ),
    )


def test_segments_are_the_canonical_six_and_unknown_is_present() -> None:
    assert SEGMENTS == (WOMAN, NONBINARY, FEMALE_FRONTED, MAN, "other", UNKNOWN)
    assert UNKNOWN in SEGMENTS


def test_identity_segment_prefers_sourced_gender_over_composition() -> None:
    assert identity_segment(make_artist("w", gender=Gender.WOMAN)) == WOMAN
    assert identity_segment(make_artist("nb", gender=Gender.NONBINARY)) == NONBINARY
    assert identity_segment(make_artist("m", gender=Gender.MAN)) == MAN
    assert identity_segment(make_artist("u")) == UNKNOWN


def test_identity_segment_female_fronted_is_composition_not_a_personal_claim() -> None:
    woman = IdentityLabel(
        gender=Gender.WOMAN,
        basis=IdentityBasis.SELF_IDENTIFIED,
        sources=(Source(SourceKind.ARTIST_STATEMENT, "c", "2026-05-31"),),
    )
    base = make_artist("band")
    band = type(base)(
        artist_id="band",
        name="Band",
        composition=BandComposition(
            members_fronting=(FrontPerson("Lead", "vocals", woman),),
            sources=(Source(SourceKind.DISCOGS_LINEUP, "c", "2026-05-31"),),
        ),
    )
    assert band.identity.gender is Gender.UNKNOWN  # the band itself has no gender
    assert identity_segment(band) == FEMALE_FRONTED


def test_unknown_retention_is_1_across_lens_strengths_on_real_reranked_output() -> None:
    """The boost-only proof, exercised on rerank's actual emitted output."""
    base_recs = [
        _rec(make_artist("man", gender=Gender.MAN), 0.9),
        _rec(make_artist("woman", gender=Gender.WOMAN), 0.4),
        _rec(make_artist("unknown-1"), 0.6),
        _rec(make_artist("unknown-2"), 0.3),
    ]
    recs_by_lens = {lens: rerank(base_recs, lens_strength=lens) for lens in (0.0, 0.25, 0.5, 1.0)}

    retention = unknown_retention(recs_by_lens, base_lens=0.0)
    assert retention == {0.0: 1.0, 0.25: 1.0, 0.5: 1.0, 1.0: 1.0}

    # The proof methods.md cites: this must not raise for real emitted output.
    assert_unknown_retained(recs_by_lens, base_lens=0.0)


def test_assert_unknown_retained_raises_on_a_downranked_unknown() -> None:
    """The guard actually guards: a synthetic violation is caught, not rubber-stamped."""
    unknown = make_artist("unknown-1")
    base = {0.0: [_rec(unknown, 0.6)]}
    violated = {0.0: [_rec(unknown, 0.6)], 0.5: [_rec(unknown, 0.4)]}  # score dropped

    assert_unknown_retained(base, base_lens=0.0)  # sanity: no violation here
    with pytest.raises(FairnessAssertionError, match="down-ranked"):
        assert_unknown_retained(violated, base_lens=0.0)


def test_assert_unknown_retained_raises_on_a_dropped_unknown() -> None:
    unknown = make_artist("unknown-1")
    violated = {0.0: [_rec(unknown, 0.6)], 0.5: []}  # dropped entirely

    with pytest.raises(FairnessAssertionError, match="dropped"):
        assert_unknown_retained(violated, base_lens=0.0)


def test_unknown_retention_is_vacuously_1_when_there_are_no_unknowns() -> None:
    recs_by_lens = {0.0: [_rec(make_artist("w", gender=Gender.WOMAN), 0.5)]}
    assert unknown_retention(recs_by_lens, base_lens=0.0) == {0.0: 1.0}
