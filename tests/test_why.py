"""'Why this artist': the explanation is transparent, sourced, and never inferred."""

from __future__ import annotations

import pytest
from pipeline.models import IdentityBasis
from recommender.hybrid import recommend
from recommender.why import (
    ProvenanceItem,
    WhyThisArtist,
    artist_identity_phrase,
    rank_shift_statement,
    why_this_artist,
)


def _rec_for(profile, catalog, source, artist_id, lens=0.5):
    for rec in recommend(profile, catalog, source, k=99, lens_strength=lens):
        if rec.artist.artist_id == artist_id:
            return rec
    raise AssertionError(f"{artist_id} not in recommendations")


def test_every_recommendation_yields_a_why(profile, catalog, source) -> None:
    for rec in recommend(profile, catalog, source, k=99, lens_strength=0.5):
        why = why_this_artist(rec)
        assert isinstance(why, WhyThisArtist)
        assert why.inferred is False  # the hard guarantee, surfaced in the output
        assert why.headline
        assert why.reasons
        assert why.identity_statement
        assert why.rank_shift  # 100% coverage: every card states its rank shift


def test_sourced_woman_shows_provenance_not_inference(profile, catalog, source) -> None:
    rec = _rec_for(profile, catalog, source, "snail-mail")
    why = why_this_artist(rec)
    assert why.identity_basis is IdentityBasis.SELF_IDENTIFIED
    assert why.identity_is_known
    assert why.provenance, "a sourced identity must carry its citations"
    for item in why.provenance:
        assert isinstance(item, ProvenanceItem)
        assert item.citation
        assert item.asserted_value  # the *raw* claim, auditable, not just a label
        assert item.retrieved_at
    # The raw asserted value and a real citation reach the rendered text.
    text = why.to_text()
    assert "sourced, never inferred" in text.lower()
    assert any(item.citation in text for item in why.provenance)


def test_unknown_is_first_class_and_honest(profile, catalog, source) -> None:
    rec = _rec_for(profile, catalog, source, "mystery-act", lens=1.0)
    why = why_this_artist(rec)
    assert why.identity_basis is IdentityBasis.UNKNOWN
    assert not why.identity_is_known
    assert why.provenance == ()
    assert "unknown" in why.identity_statement.lower()
    assert "similarity" in why.identity_statement.lower()
    # No apology, no guess — and the markdown says sources are absent, not wrong.
    assert "surfaced on merit" in why.to_markdown().lower()


def test_female_fronted_is_band_composition_not_member_gender(profile, catalog, source) -> None:
    rec = _rec_for(profile, catalog, source, "boygenius")
    why = why_this_artist(rec)
    assert why.identity_basis is IdentityBasis.BAND_COMPOSITION
    assert "female-fronted" in why.identity_statement.lower()
    assert "distinct from any member" in why.identity_statement.lower()
    assert why.provenance  # sourced lineup citation present


def test_markdown_and_text_round_trip_the_reasons(profile, catalog, source) -> None:
    rec = _rec_for(profile, catalog, source, "snail-mail")
    why = why_this_artist(rec)
    md = why.to_markdown()
    txt = why.to_text()
    assert why.artist_name in md and why.artist_name in txt
    for reason in why.reasons:
        # Reasons appear in both renderings (markdown bullet / text bullet).
        assert reason in md
        assert reason in txt
    # The rank-shift line is rendered in both text and markdown, under identity.
    assert why.rank_shift in md
    assert why.rank_shift in txt


def test_rank_shift_statement_wording() -> None:
    assert rank_shift_statement(4, 9) == "the values lens moved this pick from #9 to #4"
    assert rank_shift_statement(3, 3) == "the values lens did not change this pick's position"
    # base_rank == 0 means the counterfactual was never computed — treated as
    # unchanged rather than fabricating a shift.
    assert rank_shift_statement(5, 0) == "the values lens did not change this pick's position"


def test_rank_shift_reflects_the_boost_moving_a_pick_up(profile, catalog, source) -> None:
    # At full lens strength, boygenius (values-aligned) rises from #3 to #2.
    rec = _rec_for(profile, catalog, source, "boygenius", lens=1.0)
    assert rec.base_rank == 3
    assert rec.rank == 2
    why = why_this_artist(rec)
    assert why.rank_shift == "the values lens moved this pick from #3 to #2"


def test_rank_shift_unchanged_when_already_top(profile, catalog, source) -> None:
    # snail-mail is #1 either way at full lens strength — no shift to report.
    rec = _rec_for(profile, catalog, source, "snail-mail", lens=1.0)
    assert rec.rank == rec.base_rank == 1
    why = why_this_artist(rec)
    assert why.rank_shift == "the values lens did not change this pick's position"


def test_rank_shift_unchanged_for_everyone_at_lens_zero(profile, catalog, source) -> None:
    # Guard: lens_strength=0 must yield "unchanged" for every card, no exceptions.
    for rec in recommend(profile, catalog, source, k=99, lens_strength=0.0):
        assert rec.rank == rec.base_rank
        why = why_this_artist(rec)
        assert why.rank_shift == "the values lens did not change this pick's position"


def test_unknown_identity_never_shows_a_lens_caused_improvement(profile, catalog, source) -> None:
    """Excellence-bar invariant: the boost-only re-rank never moves an unknown
    card *up*. Its rank can only stay the same or get pushed down by aligned
    picks overtaking it — never improve, since it never receives a boost.
    """
    for rec in recommend(profile, catalog, source, k=99, lens_strength=1.0):
        why = why_this_artist(rec)
        if why.identity_basis is IdentityBasis.UNKNOWN:
            # rank - base_rank >= 0: never a smaller (better) rank number than
            # the counterfactual pure-taste position.
            assert rec.rank >= rec.base_rank, (
                f"{rec.artist.artist_id} improved from #{rec.base_rank} to "
                f"#{rec.rank} despite an unknown identity — the lens is boost-only"
            )


def test_artist_identity_phrase_matches_statement(profile, catalog, source) -> None:
    rec = _rec_for(profile, catalog, source, "snail-mail")
    assert artist_identity_phrase(rec.artist) == why_this_artist(rec).identity_statement


def test_provenance_item_from_source_preserves_raw_value() -> None:
    from pipeline.models import Source, SourceKind

    src = Source(
        kind=SourceKind.MUSICBRAINZ_GENDER,
        citation="https://musicbrainz.org/artist/x",
        retrieved_at="2026-05-31",
        detail="female",
    )
    item = ProvenanceItem.from_source(src)
    assert item.asserted_value == "female"
    assert item.source_kind == "musicbrainz-gender"
    assert item.citation == src.citation


def test_to_text_handles_no_reasons_branch() -> None:
    why = WhyThisArtist(
        artist_name="Nobody",
        headline="appears in your discovery catalog",
        reasons=(),
        identity_statement="identity unknown — surfaced on musical similarity alone",
        identity_basis=IdentityBasis.UNKNOWN,
        provenance=(),
    )
    text = why.to_text()
    assert "Nobody" in text
    assert "none" in text.lower()
    assert "Why recommended" not in text  # no reasons section when empty
    md = why.to_markdown()
    assert "Nobody" in md
    assert "surfaced on merit" in md.lower()
    assert "Why recommended" not in md  # markdown also omits the empty section


@pytest.mark.parametrize("lens", [0.0, 1.0])
def test_why_stable_across_lens(profile, catalog, source, lens) -> None:
    rec = _rec_for(profile, catalog, source, "mystery-act", lens=lens)
    why = why_this_artist(rec)
    assert why.identity_basis is IdentityBasis.UNKNOWN
