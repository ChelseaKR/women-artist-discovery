"""Metric: identity labels carrying a cited source = 100% (merge-blocking)."""

from __future__ import annotations

from pipeline.identity import IdentityEvidence, resolve_identity
from pipeline.models import Gender, SourceKind


def test_every_known_label_in_catalog_carries_a_source(catalog) -> None:
    for artist in catalog.values():
        if artist.identity.is_known:
            assert artist.identity.sources, f"{artist.name} has a gender but no source"
            for src in artist.identity.sources:
                assert src.citation.strip()
                assert src.retrieved_at.strip()


def test_every_sourced_composition_carries_a_source(catalog) -> None:
    for artist in catalog.values():
        if artist.composition is not None:
            assert artist.composition.sources


def test_resolver_attaches_all_contributing_sources() -> None:
    label = resolve_identity(
        [
            IdentityEvidence(SourceKind.MUSICBRAINZ_GENDER, "female", "mb://1", "2026-05-31"),
            IdentityEvidence(SourceKind.WIKIDATA_P21, "Q6581072", "wd://1", "2026-05-31"),
        ]
    )
    assert label.gender is Gender.WOMAN
    assert len(label.sources) == 2
    assert {s.kind for s in label.sources} == {
        SourceKind.MUSICBRAINZ_GENDER,
        SourceKind.WIKIDATA_P21,
    }


def test_recommendation_identity_sources_match_basis(profile, catalog, source) -> None:
    from pipeline.models import IdentityBasis
    from recommender.hybrid import recommend

    for rec in recommend(profile, catalog, source, lens_strength=0.5):
        expl = rec.explanation
        if expl.identity_basis is IdentityBasis.UNKNOWN:
            assert expl.identity_sources == ()
        else:
            assert expl.identity_sources, f"{rec.artist.name}: basis without sources"
