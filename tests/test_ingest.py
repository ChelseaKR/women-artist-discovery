"""Ingest orchestration: username -> stored profile + enriched catalog."""

from __future__ import annotations

from pipeline.cache import Cache
from pipeline.enrich import FixtureEnricher
from pipeline.identity import IdentityEvidence
from pipeline.ingest import (
    IdentityLabelChange,
    build_profile,
    diff_identity_sources,
    enrich_artist,
    ingest,
    refresh_catalog,
)
from pipeline.lastfm import FixtureLastfm
from pipeline.models import Gender, SourceKind


def test_build_profile_counts_plays(scrobbles, demo_user) -> None:
    profile = build_profile(demo_user, scrobbles)
    assert profile.play_counts["mitski"] == 10
    assert profile.top_artists(1) == ["mitski"]


def test_enrich_artist_resolves_sourced_identity(source, enricher) -> None:
    artist = enrich_artist("mitski", "Mitski", source, enricher)
    assert artist.identity.gender is Gender.WOMAN
    assert artist.identity.sources
    assert "indie rock" in artist.tags


def test_enrich_artist_defaults_to_unknown(source, enricher) -> None:
    artist = enrich_artist("mystery-act", "Mystery Act", source, enricher)
    assert artist.identity.gender is Gender.UNKNOWN
    assert artist.composition is None


def test_ingest_persists_to_cache(demo_user, source, enricher) -> None:
    cache = Cache(":memory:")
    try:
        profile, _catalog = ingest(
            demo_user, source, enricher, cache=cache, fetched_at="2026-05-31"
        )
        assert profile.play_counts
        # listened artists are enriched + cached with a lineage timestamp
        assert cache.get_artist("mitski") is not None
        assert cache.artist_fetched_at("mitski") == "2026-05-31"
        assert cache.get_scrobbles(demo_user)
        # tags are attached back onto the profile after enrichment
        assert profile.tags["mitski"]
    finally:
        cache.close()


def test_ingest_without_cache_still_returns_catalog(demo_user, source, enricher) -> None:
    profile, catalog = ingest(demo_user, source, enricher)
    assert set(catalog) <= set(profile.play_counts)
    assert "mitski" in catalog


# --- refresh / IdentityLabelChange (EXP-05's "fix it at the source" round-trip) --


def _lastfm() -> FixtureLastfm:
    return FixtureLastfm(scrobbles={}, tags={"mitski": ()}, similar={})


def _wikidata_enricher(retrieved_at: str) -> FixtureEnricher:
    return FixtureEnricher(
        gender={
            "mitski": [
                IdentityEvidence(
                    kind=SourceKind.WIKIDATA_P21,
                    value="Q6581072",
                    citation="https://www.wikidata.org/wiki/Q16735549",
                    retrieved_at=retrieved_at,
                )
            ]
        },
        composition={},
    )


def test_diff_identity_sources_reports_a_moved_retrieved_at() -> None:
    lastfm = _lastfm()
    old = enrich_artist("mitski", "Mitski", lastfm, _wikidata_enricher("2026-05-31"))
    new = enrich_artist("mitski", "Mitski", lastfm, _wikidata_enricher("2026-07-01"))

    changes = diff_identity_sources(old, new)

    assert changes == [
        IdentityLabelChange(
            artist_id="mitski",
            source_kind="wikidata-p21",
            old_value="Q6581072",
            new_value="Q6581072",
            retrieved_at="2026-07-01",
        )
    ]


def test_diff_identity_sources_is_empty_when_nothing_changed() -> None:
    lastfm = _lastfm()
    enricher = _wikidata_enricher("2026-05-31")
    a = enrich_artist("mitski", "Mitski", lastfm, enricher)
    b = enrich_artist("mitski", "Mitski", lastfm, enricher)
    assert diff_identity_sources(a, b) == []


def test_refresh_catalog_updates_cache_lineage_and_returns_changes() -> None:
    lastfm = _lastfm()
    cache = Cache(":memory:")
    try:
        artist = enrich_artist(
            "mitski",
            "Mitski",
            lastfm,
            _wikidata_enricher("2026-05-31"),
            listeners=1_200_000,
            playcount=42,
        )
        cache.put_artist(artist, fetched_at="2026-05-31")

        changes = refresh_catalog(
            cache, lastfm, _wikidata_enricher("2026-07-01"), fetched_at="2026-07-01"
        )

        assert len(changes) == 1
        assert changes[0].artist_id == "mitski"
        assert changes[0].retrieved_at == "2026-07-01"
        assert cache.artist_fetched_at("mitski") == "2026-07-01"
        refreshed = cache.get_artist("mitski")
        assert refreshed is not None
        assert refreshed.listeners == 1_200_000  # popularity preserved across refresh
    finally:
        cache.close()


def test_refresh_catalog_on_empty_cache_is_a_noop() -> None:
    cache = Cache(":memory:")
    try:
        changes = refresh_catalog(
            cache, _lastfm(), _wikidata_enricher("2026-07-01"), fetched_at="2026-07-01"
        )
        assert changes == []
    finally:
        cache.close()


def test_cache_list_artist_ids_reflects_puts() -> None:
    cache = Cache(":memory:")
    try:
        assert cache.list_artist_ids() == []
        artist = enrich_artist("mitski", "Mitski", _lastfm(), _wikidata_enricher("2026-05-31"))
        cache.put_artist(artist, fetched_at="2026-05-31")
        assert cache.list_artist_ids() == ["mitski"]
    finally:
        cache.close()
