"""Re-rank math + the boost-only contract, on hand-built artists."""

from __future__ import annotations

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
from recommender.rerank import MAX_BOOST, rerank, values_boost_for_artist

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


def test_boost_scales_with_lens_strength() -> None:
    woman = make_artist("w", gender=Gender.WOMAN)
    assert values_boost_for_artist(woman, 0.0) == 0.0
    assert values_boost_for_artist(woman, 0.5) == MAX_BOOST * 0.5
    assert values_boost_for_artist(woman, 1.0) == MAX_BOOST


def test_nonbinary_is_boosted_like_women() -> None:
    nb = make_artist("nb", gender=Gender.NONBINARY)
    assert values_boost_for_artist(nb, 1.0) == MAX_BOOST


def test_man_and_unknown_get_no_boost() -> None:
    assert values_boost_for_artist(make_artist("m", gender=Gender.MAN), 1.0) == 0.0
    assert values_boost_for_artist(make_artist("u"), 1.0) == 0.0


def test_female_fronted_band_is_boosted_via_composition() -> None:
    woman = IdentityLabel(
        gender=Gender.WOMAN,
        basis=IdentityBasis.SELF_IDENTIFIED,
        sources=(Source(SourceKind.ARTIST_STATEMENT, "c", "2026-05-31"),),
    )
    band = make_artist("band")
    band = type(band)(
        artist_id="band",
        name="Band",
        composition=BandComposition(
            members_fronting=(FrontPerson("Lead", "vocals", woman),),
            sources=(Source(SourceKind.DISCOGS_LINEUP, "c", "2026-05-31"),),
        ),
    )
    assert band.identity.gender is Gender.UNKNOWN  # the band itself has no gender
    assert band.female_fronted is True
    assert values_boost_for_artist(band, 1.0) == MAX_BOOST


def test_lens_zero_preserves_pure_taste_order() -> None:
    recs = [
        _rec(make_artist("man", gender=Gender.MAN), 0.9),
        _rec(make_artist("woman", gender=Gender.WOMAN), 0.4),
    ]
    out = rerank(recs, lens_strength=0.0)
    assert [r.artist.artist_id for r in out] == ["man", "woman"]


def test_lens_can_reorder_upward_only() -> None:
    recs = [
        _rec(make_artist("man", gender=Gender.MAN), 0.9),
        _rec(make_artist("woman", gender=Gender.WOMAN), 0.7),
    ]
    out = {r.artist.artist_id: r for r in rerank(recs, lens_strength=1.0)}
    # The man keeps 0.9; the woman rises to 0.7 + MAX_BOOST and overtakes.
    assert out["man"].score == 0.9
    assert out["woman"].score == 0.7 + MAX_BOOST
    assert out["woman"].rank == 1 and out["man"].rank == 2
