"""Ingest orchestration: username -> stored profile + enriched catalog."""

from __future__ import annotations

from pipeline.cache import Cache
from pipeline.ingest import build_profile, enrich_artist, ingest
from pipeline.lastfm import FixtureLastfm
from pipeline.models import Gender, Scrobble


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


# --- FIX-02: paginated, incremental, resumable ingest -----------------------


class _RecordingFixtureLastfm(FixtureLastfm):
    """Wraps FixtureLastfm to record each `scrobbles_since` call's since_ts.

    Lets tests assert *what was asked for*, not just what came back — the
    difference between "ingest re-fetched the whole history and happened to
    merge cleanly" and "ingest only asked for what's new".
    """

    def __init__(self, *a: object, **kw: object) -> None:
        super().__init__(*a, **kw)  # type: ignore[arg-type]
        self.since_calls: list[int] = []

    def scrobbles_since(
        self, username: str, since_ts: int = 0, page_size: int = 200
    ) -> list[Scrobble]:
        self.since_calls.append(since_ts)
        return super().scrobbles_since(username, since_ts=since_ts, page_size=page_size)


def _make_history(n: int, start_ts: int = 1_000_000) -> list[Scrobble]:
    """`n` scrobbles of a single artist, one per second, strictly increasing ts."""
    return [Scrobble("mitski", "Mitski", f"track-{i}", start_ts + i) for i in range(n)]


def test_first_sync_paginates_full_history(demo_user, enricher) -> None:
    """A history far larger than one page is ingested in full via scrobbles_since."""
    history = _make_history(450)  # several pages at the default page_size=200
    source = FixtureLastfm(scrobbles={demo_user: history}, tags={}, similar={})
    cache = Cache(":memory:")
    try:
        profile, _catalog = ingest(demo_user, source, enricher, cache=cache, limit=50)
        assert profile.play_counts["mitski"] == 450
        assert len(cache.get_scrobbles(demo_user)) == 450
        assert cache.last_synced_ts(demo_user) == history[-1].ts
    finally:
        cache.close()


def test_incremental_second_sync_fetches_only_new_scrobbles(demo_user, enricher) -> None:
    """A second ingest only requests ts > watermark, but the profile reflects everything."""
    first_batch = _make_history(300, start_ts=1_000_000)
    source = _RecordingFixtureLastfm(scrobbles={demo_user: list(first_batch)}, tags={}, similar={})
    cache = Cache(":memory:")
    try:
        profile, _catalog = ingest(demo_user, source, enricher, cache=cache, limit=100)
        assert profile.play_counts["mitski"] == 300
        assert source.since_calls == [0]  # first sync starts from the beginning

        watermark = cache.last_synced_ts(demo_user)
        new_batch = _make_history(20, start_ts=watermark + 1000)
        source._scrobbles[demo_user] = first_batch + new_batch

        profile2, _catalog2 = ingest(demo_user, source, enricher, cache=cache, limit=100)
        # the incremental call asked only for what's new...
        assert source.since_calls[-1] == watermark
        # ...but the resulting profile reflects the full merged history
        assert profile2.play_counts["mitski"] == 320
        assert len(cache.get_scrobbles(demo_user)) == 320
    finally:
        cache.close()


def test_repeated_ingest_of_same_history_yields_stable_play_counts(demo_user, enricher) -> None:
    """Idempotency: re-ingesting an unchanged history never inflates play counts."""
    history = _make_history(120)
    source = FixtureLastfm(scrobbles={demo_user: history}, tags={}, similar={})
    cache = Cache(":memory:")
    try:
        profile1, _ = ingest(demo_user, source, enricher, cache=cache, limit=40)
        profile2, _ = ingest(demo_user, source, enricher, cache=cache, limit=40)
        profile3, _ = ingest(demo_user, source, enricher, cache=cache, limit=40)
        assert profile1.play_counts["mitski"] == 120
        assert profile2.play_counts == profile1.play_counts
        assert profile3.play_counts == profile1.play_counts
        assert len(cache.get_scrobbles(demo_user)) == 120
    finally:
        cache.close()
