"""Ingest orchestration: username -> stored profile + enriched catalog."""

from __future__ import annotations

import logging

import pytest
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
        profile, catalog = ingest(demo_user, source, enricher, cache=cache, fetched_at="2026-05-31")
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


class _FailingSource:
    """A ScrobbleSource whose fetch stage always raises (FIX-12 failure logging)."""

    def recent_scrobbles(self, username: str, limit: int = 200):  # noqa: ANN201
        raise RuntimeError("simulated Last.fm failure")

    def artist_tags(self, artist_id: str) -> tuple[str, ...]:
        return ()

    def similar_artists(self, artist_id: str) -> list[tuple[str, float]]:
        return []


class _FailingEnricher:
    """An EnrichmentSource whose gender lookup always raises (FIX-12 failure logging)."""

    def gender_evidence(self, artist_id: str):  # noqa: ANN201
        raise RuntimeError("simulated enrichment-source failure")

    def composition_evidence(self, artist_id: str):  # noqa: ANN201
        return [], []


def test_ingest_logs_and_reraises_scrobble_fetch_failure(demo_user, enricher, caplog) -> None:
    with (
        caplog.at_level(logging.ERROR, logger="wad.ingest"),
        pytest.raises(RuntimeError, match="simulated Last.fm failure"),
    ):
        ingest(demo_user, _FailingSource(), enricher)
    assert "stage=fetch_scrobbles" in caplog.text
    assert "event=failed" in caplog.text


def test_ingest_logs_and_reraises_enrich_failure(demo_user, source, caplog) -> None:
    with (
        caplog.at_level(logging.ERROR, logger="wad.ingest"),
        pytest.raises(RuntimeError, match="simulated enrichment-source failure"),
    ):
        ingest(demo_user, source, _FailingEnricher())
    assert "stage=enrich" in caplog.text
    assert "event=failed" in caplog.text
