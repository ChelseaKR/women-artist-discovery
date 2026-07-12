"""Ingest orchestration: username -> stored profile + enriched catalog."""

from __future__ import annotations

from pipeline.cache import Cache
from pipeline.ingest import build_profile, enrich_artist, ingest
from pipeline.models import Gender


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
