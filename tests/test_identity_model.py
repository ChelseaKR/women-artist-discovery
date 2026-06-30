"""Bias audit §B: nonbinary representable end-to-end; female-fronted distinct."""

from __future__ import annotations

from pipeline.identity import IdentityEvidence, resolve_composition, resolve_identity
from pipeline.models import FrontPerson, Gender, IdentityBasis, SourceKind
from recommender.hybrid import recommend


def test_nonbinary_resolves_from_sourced_statement(nonbinary_label) -> None:
    assert nonbinary_label.gender is Gender.NONBINARY
    assert nonbinary_label.basis is IdentityBasis.SELF_IDENTIFIED
    assert nonbinary_label.sources


def test_nonbinary_survives_end_to_end_in_recommendations(profile, catalog, source) -> None:
    recs = recommend(profile, catalog, source, k=99, lens_strength=1.0)
    shamir = next(r for r in recs if r.artist.artist_id == "shamir")
    assert shamir.artist.identity.gender is Gender.NONBINARY
    assert shamir.rerank_delta > 0.0  # nonbinary is values-aligned and boosted
    assert "nonbinary" in shamir.explanation.summary.lower()


def test_wikidata_qids_map_respectfully() -> None:
    cases = {
        "Q6581072": Gender.WOMAN,  # female
        "Q1052281": Gender.WOMAN,  # trans woman IS a woman
        "Q6581097": Gender.MAN,
        "Q2449503": Gender.MAN,  # trans man IS a man
        "Q48270": Gender.NONBINARY,
        "Q1097630": Gender.OTHER,  # intersex represented, not flattened to unknown
    }
    for qid, expected in cases.items():
        label = resolve_identity(
            [IdentityEvidence(SourceKind.WIKIDATA_P21, qid, "wd://x", "2026-05-31")]
        )
        assert label.gender is expected, qid


def test_unrecognised_qid_stays_unknown() -> None:
    label = resolve_identity(
        [IdentityEvidence(SourceKind.WIKIDATA_P21, "Q999999999", "wd://x", "2026-05-31")]
    )
    assert label.gender is Gender.UNKNOWN


def test_female_fronted_is_distinct_from_member_gender() -> None:
    """The band has no personal gender; the member keeps her own sourced label."""
    member = resolve_identity(
        [IdentityEvidence(SourceKind.ARTIST_STATEMENT, "woman", "c", "2026-05-31")]
    )
    fronts = [FrontPerson("Singer", "lead vocals", member)]
    comp = resolve_composition(
        fronts,
        [IdentityEvidence(SourceKind.DISCOGS_LINEUP, "lineup", "c", "2026-05-31")],
    )
    assert comp is not None
    assert comp.female_fronted is True
    # The member's gender is still her own self-ID, not the band's.
    assert comp.members_fronting[0].identity.gender is Gender.WOMAN


def test_conflicting_sources_lower_confidence() -> None:
    label = resolve_identity(
        [
            IdentityEvidence(SourceKind.ARTIST_STATEMENT, "woman", "c1", "2026-05-31"),
            IdentityEvidence(SourceKind.MUSICBRAINZ_GENDER, "male", "c2", "2026-05-31"),
        ]
    )
    # Highest-priority source (artist statement) wins, but confidence is hedged.
    assert label.gender is Gender.WOMAN
    assert label.confidence is not None and label.confidence <= 0.5
