"""Fairness observability panel: exposure share + the unknown-retention curve.

Mirrors the excellence bar tested in ``tests/test_unknown_first_class.py`` but at
the *aggregate* (exposure) level rather than the single-recommendation level:
moving the lens must be free to reshape exposure share across identity segments,
but must never displace an unknown-identity artist that was already surfaced
within the window being observed.
"""

from __future__ import annotations

import pytest
from pipeline.models import (
    Artist,
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
    SEGMENTS,
    exposure_at_k,
    exposure_report,
    identity_segment,
    observability_panel,
    rank_shift,
    unknown_retention,
)
from recommender.hybrid import recommend
from recommender.rerank import rerank

from .conftest import make_artist


def _band_artist(aid: str) -> Artist:
    """A sourced female-fronted band — aligned via *composition*, never personal gender."""
    woman = IdentityLabel(
        gender=Gender.WOMAN,
        basis=IdentityBasis.SELF_IDENTIFIED,
        sources=(Source(SourceKind.ARTIST_STATEMENT, "https://example.org/lead", "2026-05-31"),),
    )
    return Artist(
        artist_id=aid,
        name=aid.title(),
        composition=BandComposition(
            members_fronting=(FrontPerson("Lead", "vocals", woman),),
            sources=(
                Source(SourceKind.DISCOGS_LINEUP, "https://example.org/lineup", "2026-05-31"),
            ),
        ),
    )


def _rec(artist: Artist, base: float, *, basis: IdentityBasis) -> Recommendation:
    sources = (
        artist.composition.sources
        if basis is IdentityBasis.BAND_COMPOSITION and artist.composition
        else artist.identity.sources
    )
    explanation = Explanation(
        signals=(Signal("content", "shared tags", 1.0),),
        identity_basis=basis,
        identity_sources=sources,
        summary="why",
    )
    return Recommendation(artist=artist, base_score=base, rerank_delta=0.0, explanation=explanation)


def _base_recs() -> list[Recommendation]:
    """A small candidate set spanning every segment, boost-crafted so that:

    * ``u1`` (unknown) never receives a boost and starts with the highest base
      score, so it stays in the top-2 at every lens — the retention guarantee.
    * which *segment* fills the other top-2 slot flips from self-identified
      (``m1``, a sourced man — not boosted) to band-composition (``b1``, a
      sourced female-fronted band — boosted) as the lens strengthens — the
      exposure-share guarantee has real room to move.
    """
    return [
        _rec(make_artist("u1"), 0.90, basis=IdentityBasis.UNKNOWN),
        _rec(make_artist("m1", gender=Gender.MAN), 0.60, basis=IdentityBasis.SELF_IDENTIFIED),
        _rec(_band_artist("b1"), 0.55, basis=IdentityBasis.BAND_COMPOSITION),
        _rec(make_artist("w2", gender=Gender.WOMAN), 0.40, basis=IdentityBasis.SELF_IDENTIFIED),
    ]


def _recs_by_lens(k: int = 2) -> dict[float, list[Recommendation]]:
    base = _base_recs()
    return {lens: rerank(base, lens_strength=lens) for lens in (0.0, 0.25, 0.5, 0.75, 1.0)}


# --- identity_segment / exposure_at_k -----------------------------------------


def test_identity_segment_reads_the_sourced_basis_never_infers() -> None:
    recs = _base_recs()
    assert identity_segment(recs[0]) == "unknown"
    assert identity_segment(recs[1]) == "self-identified"
    assert identity_segment(recs[2]) == "band-composition"


def test_exposure_at_k_shares_sum_to_one() -> None:
    recs = rerank(_base_recs(), lens_strength=0.0)
    shares = exposure_at_k(recs, k=4)
    assert set(shares) == set(SEGMENTS)
    assert abs(sum(shares.values()) - 1.0) < 1e-9


def test_exposure_at_k_empty_top_k_reports_zeros_not_a_crash() -> None:
    shares = exposure_at_k([], k=5)
    assert shares == dict.fromkeys(SEGMENTS, 0.0)


def test_exposure_shares_differ_between_lens_0_and_lens_1() -> None:
    """The lens is free to reshape *which segment* holds a top-k slot."""
    lens0 = rerank(_base_recs(), lens_strength=0.0)
    lens1 = rerank(_base_recs(), lens_strength=1.0)
    shares0 = exposure_at_k(lens0, k=2)
    shares1 = exposure_at_k(lens1, k=2)
    assert shares0 != shares1
    assert any(shares0[seg] != shares1[seg] for seg in SEGMENTS)
    # Concretely: self-identified share drops as band-composition rises.
    assert shares0["self-identified"] > shares1["self-identified"]
    assert shares0["band-composition"] < shares1["band-composition"]


def test_exposure_shares_also_differ_on_the_demo_world_when_k_truncates(
    profile, catalog, source
) -> None:
    """Same property against real (non-hand-built) recommendations."""
    lens0 = recommend(profile, catalog, source, k=3, lens_strength=0.0)
    lens1 = recommend(profile, catalog, source, k=3, lens_strength=1.0)
    assert exposure_at_k(lens0, k=3) != exposure_at_k(lens1, k=3)


# --- unknown_retention --------------------------------------------------------


def test_unknown_retention_is_pinned_at_one_across_every_lens() -> None:
    base = rerank(_base_recs(), lens_strength=0.0)
    for lens in (0.0, 0.25, 0.5, 0.75, 1.0):
        current = rerank(_base_recs(), lens_strength=lens)
        assert unknown_retention(base, current, k=2) == 1.0


def test_unknown_retention_with_no_unknown_artists_in_base_is_vacuously_one() -> None:
    recs = [
        _rec(make_artist("m1", gender=Gender.MAN), 0.5, basis=IdentityBasis.SELF_IDENTIFIED),
        _rec(make_artist("w1", gender=Gender.WOMAN), 0.4, basis=IdentityBasis.SELF_IDENTIFIED),
    ]
    assert unknown_retention(recs, recs, k=2) == 1.0


def test_unknown_retention_reports_less_than_one_when_actually_displaced() -> None:
    """Sanity check the metric is honest, not hard-coded to 1.0."""
    base = [
        _rec(make_artist("u1"), 0.9, basis=IdentityBasis.UNKNOWN),
        _rec(make_artist("m1", gender=Gender.MAN), 0.1, basis=IdentityBasis.SELF_IDENTIFIED),
    ]
    current = [
        _rec(make_artist("m1", gender=Gender.MAN), 0.1, basis=IdentityBasis.SELF_IDENTIFIED),
        _rec(make_artist("u1"), 0.9, basis=IdentityBasis.UNKNOWN),
    ]
    # u1 fills base's top-1 slot but not this (contrived) top-1 slice of current.
    assert unknown_retention(base, current, k=1) == 0.0
    assert unknown_retention(base, current, k=2) == 1.0


# --- rank_shift ----------------------------------------------------------------


def test_rank_shift_reports_signed_delta_for_shared_artists() -> None:
    base = rerank(_base_recs(), lens_strength=0.0)  # ranks: u1 1, m1 2, b1 3, w2 4
    current = rerank(_base_recs(), lens_strength=1.0)  # ranks: b1 1, u1 2, w2 3, m1 4
    shift = rank_shift(base, current)
    assert set(shift) == {"u1", "m1", "b1", "w2"}
    assert shift["b1"] > 0  # b1 moves up (boosted past everyone but nothing above it)
    assert shift["m1"] < 0  # m1 moves down (never boosted, others overtake it)
    assert shift["u1"] == -1  # u1's own score never changes, but its *rank* can slip


# --- exposure_report / observability_panel --------------------------------------


def test_exposure_report_defaults_base_lens_to_the_smallest_present() -> None:
    report = exposure_report(_recs_by_lens(), k=2)
    assert report["base_lens"] == 0.0
    assert set(report["lenses"]) == {"0", "0.25", "0.5", "0.75", "1"}


def test_exposure_report_rejects_a_base_lens_not_present() -> None:
    with pytest.raises(ValueError, match="base_lens"):
        exposure_report(_recs_by_lens(), k=2, base_lens=0.4)


def test_exposure_report_on_empty_input_reports_no_lenses() -> None:
    assert exposure_report({}, k=2) == {"k": 2, "base_lens": None, "lenses": {}}


def test_observability_panel_exposure_rows_are_aligned_to_segments() -> None:
    panel = observability_panel(_recs_by_lens(), current_lens=1.0, k=2, base_lens=0.0)
    assert [row["segment"] for row in panel["exposure_rows"]] == list(SEGMENTS)
    assert panel["base_lens"] == 0.0
    assert panel["current_lens"] == 1.0


def test_observability_panel_exposure_rows_differ_for_at_least_one_segment() -> None:
    panel = observability_panel(_recs_by_lens(), current_lens=1.0, k=2, base_lens=0.0)
    assert any(row["base_share"] != row["current_share"] for row in panel["exposure_rows"])


def test_observability_panel_retention_row_is_pinned_at_one_at_every_lens() -> None:
    panel = observability_panel(_recs_by_lens(), current_lens=0.75, k=2, base_lens=0.0)
    retention_row = panel["retention_row"]
    assert retention_row["segment"] == "unknown"
    by_lens = retention_row["by_lens"]
    assert set(by_lens) == {"0", "0.25", "0.5", "0.75", "1"}
    assert all(value == 1.0 for value in by_lens.values())


def test_observability_panel_rank_shift_row_reflects_current_vs_base() -> None:
    panel = observability_panel(_recs_by_lens(), current_lens=1.0, k=2, base_lens=0.0)
    shift = panel["rank_shift_row"]
    assert shift["b1"] > 0  # band-composition artist rises with the lens
    assert shift["u1"] < 0  # unknown's own score is invariant, but rank can slip


def test_observability_panel_rejects_a_current_lens_not_present() -> None:
    with pytest.raises(ValueError, match="current_lens"):
        observability_panel(_recs_by_lens(), current_lens=0.9, k=2, base_lens=0.0)
