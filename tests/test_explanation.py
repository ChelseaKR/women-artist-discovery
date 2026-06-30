"""Metrics: 'why recommended' present = 100%; identity basis + source shown."""

from __future__ import annotations

import pytest
from pipeline.models import Explanation, IdentityBasis, Signal
from recommender.hybrid import recommend


@pytest.mark.parametrize("lens", [0.0, 0.5, 1.0])
def test_every_recommendation_has_a_why(profile, catalog, source, lens) -> None:
    recs = recommend(profile, catalog, source, k=99, lens_strength=lens)
    assert recs
    for rec in recs:
        assert rec.explanation.signals, f"{rec.artist.name} has no signals"
        assert rec.explanation.summary.strip()


def test_every_recommendation_shows_basis_and_sources(profile, catalog, source) -> None:
    for rec in recommend(profile, catalog, source, k=99, lens_strength=0.5):
        expl = rec.explanation
        assert isinstance(expl.identity_basis, IdentityBasis)
        if expl.identity_basis is not IdentityBasis.UNKNOWN:
            assert expl.identity_sources


def test_unknown_artist_explained_respectfully(profile, catalog, source) -> None:
    rec = next(
        r
        for r in recommend(profile, catalog, source, k=99, lens_strength=1.0)
        if r.artist.artist_id == "mystery-act"
    )
    assert rec.explanation.identity_basis is IdentityBasis.UNKNOWN
    assert "unknown" in rec.explanation.summary.lower()
    assert "similarity" in rec.explanation.summary.lower()


def test_explanation_rejects_empty_signals() -> None:
    with pytest.raises(ValueError):
        Explanation(
            signals=(), identity_basis=IdentityBasis.UNKNOWN, identity_sources=(), summary="x"
        )


def test_explanation_rejects_blank_summary() -> None:
    with pytest.raises(ValueError):
        Explanation(
            signals=(Signal("content", "d", 1.0),),
            identity_basis=IdentityBasis.UNKNOWN,
            identity_sources=(),
            summary="   ",
        )
