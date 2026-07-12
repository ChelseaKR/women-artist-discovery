"""Cache + serialisation: round-trip fidelity, lineage timestamps, guardrail on load."""

from __future__ import annotations

import pytest
from pipeline.cache import Cache
from pipeline.models import (
    Artist,
    Gender,
    IdentityBasis,
    IdentityLabel,
    Scrobble,
    Source,
    SourceKind,
    UnsourcedIdentityError,
)
from pipeline.serde import artist_from_dict, artist_to_dict


@pytest.fixture
def mem_cache():
    cache = Cache(":memory:")
    yield cache
    cache.close()


def test_artist_round_trips_through_cache(mem_cache, catalog) -> None:
    artist = catalog["mitski"]
    mem_cache.put_artist(artist, fetched_at="2026-05-31")
    loaded = mem_cache.get_artist("mitski")
    assert loaded == artist
    assert mem_cache.artist_fetched_at("mitski") == "2026-05-31"  # lineage preserved


def test_missing_artist_returns_none(mem_cache) -> None:
    assert mem_cache.get_artist("nope") is None
    assert mem_cache.artist_fetched_at("nope") is None


def test_scrobbles_round_trip_ordered(mem_cache) -> None:
    scrobbles = [
        Scrobble("a", "A", "t2", 200),
        Scrobble("a", "A", "t1", 100),
    ]
    mem_cache.put_scrobbles("user", scrobbles)
    loaded = mem_cache.get_scrobbles("user")
    assert [s.ts for s in loaded] == [100, 200]  # ordered by ts


def test_last_synced_ts_is_zero_for_unknown_user(mem_cache) -> None:
    """No history yet -> the since-cursor for a full first sync (FIX-02)."""
    assert mem_cache.last_synced_ts("nobody") == 0


def test_last_synced_ts_tracks_the_newest_scrobble(mem_cache) -> None:
    mem_cache.put_scrobbles(
        "user",
        [
            Scrobble("a", "A", "t1", 100),
            Scrobble("a", "A", "t2", 300),
            Scrobble("a", "A", "t3", 200),
        ],
    )
    assert mem_cache.last_synced_ts("user") == 300
    # unrelated users don't share a watermark
    assert mem_cache.last_synced_ts("someone-else") == 0


def test_http_cache_roundtrip(mem_cache) -> None:
    assert mem_cache.get_cached_response("u://1") is None
    mem_cache.put_cached_response("u://1", "body", "2026-05-31")
    assert mem_cache.get_cached_response("u://1") == "body"


def test_composition_round_trips(mem_cache, catalog) -> None:
    band = catalog["big-thief"]
    assert band.female_fronted is True
    mem_cache.put_artist(band, fetched_at="2026-05-31")
    loaded = mem_cache.get_artist("big-thief")
    assert loaded is not None and loaded.female_fronted is True


def test_corrupt_cache_row_violating_guardrail_raises_on_load() -> None:
    """A tampered row with a gender but no source must not load as a clean label."""
    payload = {
        "artist_id": "x",
        "name": "X",
        "tags": [],
        "identity": {
            "gender": "woman",
            "basis": "self-identified",
            "sources": [],
            "confidence": None,
        },
        "composition": None,
        "listeners": 0,
        "playcount": 0,
    }
    with pytest.raises(UnsourcedIdentityError):
        artist_from_dict(payload)


def test_artist_to_dict_is_json_shaped() -> None:
    artist = Artist(
        "x",
        "X",
        identity=IdentityLabel(
            gender=Gender.WOMAN,
            basis=IdentityBasis.SELF_IDENTIFIED,
            sources=(Source(SourceKind.WIKIDATA_P21, "c", "2026-05-31", "Q1"),),
            confidence=0.8,
        ),
    )
    d = artist_to_dict(artist)
    assert d["identity"]["gender"] == "woman"
    assert d["identity"]["sources"][0]["kind"] == "wikidata-p21"
    assert artist_from_dict(d) == artist
