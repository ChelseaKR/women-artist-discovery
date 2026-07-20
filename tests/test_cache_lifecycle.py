"""FIX-04: cache lifecycle — dedupe, TTL, schema versioning/migrations, refresh.

The cache backs *identity claims*, so its lifecycle is a responsible-tech surface:
a stale cached claim must be re-checkable (TTL / ``wad refresh``), re-ingesting the
same history must not double play weights (dedupe), and a schema mismatch must fail
loudly rather than silently misread (versioning).
"""

from __future__ import annotations

import sqlite3

import pytest
from pipeline.cache import (
    CACHE_SCHEMA_VERSION,
    Cache,
    CacheSchemaError,
)
from pipeline.cli import main as cli_main
from pipeline.ingest import refresh_catalog
from pipeline.models import Gender, Scrobble

from .conftest import make_artist


@pytest.fixture
def mem_cache():
    cache = Cache(":memory:")
    yield cache
    cache.close()


# -- schema versioning / migrations -------------------------------------------


def test_fresh_cache_is_stamped_with_current_schema_version(tmp_path) -> None:
    with Cache(tmp_path / "cache.db") as cache:
        assert cache.schema_version == CACHE_SCHEMA_VERSION


def test_legacy_unversioned_cache_migrates_in_place_and_dedupes(tmp_path) -> None:
    """A pre-versioning cache (user_version=0) with duplicate scrobbles is repaired."""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE artists (artist_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                              fetched_at TEXT NOT NULL);
        CREATE TABLE scrobbles (username TEXT NOT NULL, artist_id TEXT NOT NULL,
                                artist_name TEXT NOT NULL, track TEXT NOT NULL,
                                ts INTEGER NOT NULL);
        CREATE TABLE http_cache (url TEXT PRIMARY KEY, body TEXT NOT NULL,
                                 fetched_at TEXT NOT NULL);
        """
    )
    dup = ("u", "mitski", "Mitski", "Geyser", 100)
    conn.executemany(
        "INSERT INTO scrobbles(username, artist_id, artist_name, track, ts) VALUES (?, ?, ?, ?, ?)",
        [dup, dup, ("u", "mitski", "Mitski", "Geyser", 200)],
    )
    conn.commit()
    conn.close()

    with Cache(db) as cache:
        assert cache.schema_version == CACHE_SCHEMA_VERSION
        loaded = cache.get_scrobbles("u")
        assert [s.ts for s in loaded] == [100, 200]  # duplicate row collapsed


def test_cache_from_a_newer_version_fails_loudly(tmp_path) -> None:
    db = tmp_path / "future.db"
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {CACHE_SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(CacheSchemaError):
        Cache(db)


# -- dedupe (idempotent re-ingest) ---------------------------------------------


def test_reingesting_the_same_scrobbles_is_idempotent(tmp_path) -> None:
    scrobbles = [
        Scrobble("mitski", "Mitski", "Geyser", 100),
        Scrobble("mitski", "Mitski", "Nobody", 200),
    ]
    with Cache(tmp_path / "cache.db") as cache:
        cache.put_scrobbles("u", scrobbles)
        cache.put_scrobbles("u", scrobbles)  # re-ingest of the same history
        assert len(cache.get_scrobbles("u")) == 2  # no duplicate play weights


# -- http-cache TTL --------------------------------------------------------------


def test_cached_response_within_ttl_is_a_hit(mem_cache) -> None:
    mem_cache.put_cached_response("u://1", "body", "2026-06-20")
    assert mem_cache.get_cached_response("u://1", ttl_days=30, now="2026-07-09") == "body"


def test_cached_response_past_ttl_is_a_miss(mem_cache) -> None:
    mem_cache.put_cached_response("u://1", "body", "2026-01-01")
    assert mem_cache.get_cached_response("u://1", ttl_days=30, now="2026-07-09") is None


def test_no_ttl_preserves_never_expire_behaviour(mem_cache) -> None:
    mem_cache.put_cached_response("u://1", "body", "1999-01-01")
    assert mem_cache.get_cached_response("u://1") == "body"


def test_unparseable_lineage_is_treated_as_stale(mem_cache) -> None:
    mem_cache.put_cached_response("u://1", "body", "not-a-date")
    assert mem_cache.get_cached_response("u://1", ttl_days=3650, now="2026-07-09") is None


def test_expire_http_cache_deletes_only_stale_rows(mem_cache) -> None:
    mem_cache.put_cached_response("u://old", "old", "2026-01-01")
    mem_cache.put_cached_response("u://new", "new", "2026-07-01")
    removed = mem_cache.expire_http_cache(ttl_days=30, now="2026-07-09")
    assert removed == 1
    assert mem_cache.get_cached_response("u://old") is None
    assert mem_cache.get_cached_response("u://new") == "new"


# -- refresh_catalog (the correction path) ---------------------------------------


def test_refresh_reports_identity_label_changes_with_before_and_after(mem_cache) -> None:
    old = make_artist("corrected", gender=Gender.UNKNOWN)
    new = make_artist("corrected", gender=Gender.WOMAN)
    mem_cache.put_artist(old, fetched_at="2026-06-01")
    changes = refresh_catalog(mem_cache, {"corrected": new}, fetched_at="2026-07-09")
    assert len(changes) == 1
    assert changes[0].artist_id == "corrected"
    assert changes[0].old.gender is Gender.UNKNOWN
    assert changes[0].new.gender is Gender.WOMAN
    # and the corrected label is what the cache now holds:
    stored = mem_cache.get_artist("corrected")
    assert stored is not None and stored.identity.gender is Gender.WOMAN


def test_refresh_is_silent_for_unchanged_and_new_artists(mem_cache) -> None:
    unchanged = make_artist("same", gender=Gender.NONBINARY)
    mem_cache.put_artist(unchanged, fetched_at="2026-06-01")
    brand_new = make_artist("new-artist", gender=Gender.UNKNOWN)
    changes = refresh_catalog(
        mem_cache, {"same": unchanged, "new-artist": brand_new}, fetched_at="2026-07-09"
    )
    assert changes == []  # nothing changed, nothing invented
    assert mem_cache.get_artist("new-artist") is not None  # but the new artist is stored


# -- `wad refresh` CLI -------------------------------------------------------------


def test_cli_refresh_populates_a_fresh_cache_and_exits_zero(tmp_path, capsys) -> None:
    db = tmp_path / "cache.db"
    assert cli_main(["refresh", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "DEMO ONLY" in out
    assert "no upstream identity API was queried" in out
    assert "no identity-label changes" in out
    assert "expired 0 stale http-cache row(s)" in out
    with Cache(db) as cache:
        assert cache.get_artist("mitski") is not None  # demo catalog was persisted


def test_cli_refresh_unknown_artist_fails(tmp_path, capsys) -> None:
    assert cli_main(["refresh", "--db", str(tmp_path / "c.db"), "--artist", "nope"]) == 1
    assert "no such artist" in capsys.readouterr().err


def test_cli_refresh_rejects_negative_ttl(tmp_path) -> None:
    with pytest.raises(SystemExit) as exc:
        cli_main(["refresh", "--db", str(tmp_path / "c.db"), "--ttl-days", "-1"])
    assert exc.value.code == 2
