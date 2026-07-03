"""Ingest orchestration: username -> stored listening profile + enriched catalog.

Ties together the :class:`~pipeline.lastfm.ScrobbleSource`, the
:class:`~pipeline.enrich.EnrichmentSource`, the identity resolver, and the local
:class:`~pipeline.cache.Cache`. The result is:

* a :class:`~pipeline.models.ListeningProfile` (per-artist play weights + tags), and
* a catalog of enriched :class:`~pipeline.models.Artist` objects with *sourced*
  identity + composition (defaulting to unknown), each cached with a fetch date.
"""

from __future__ import annotations

from typing import Optional

from pipeline.cache import Cache
from pipeline.enrich import EnrichmentSource
from pipeline.identity import resolve_composition, resolve_identity
from pipeline.lastfm import ScrobbleSource
from pipeline.models import Artist, ListeningProfile, Scrobble


def build_profile(
    username: str,
    scrobbles: list[Scrobble],
    *,
    now_ts: Optional[int] = None,
    half_life_days: Optional[float] = None,
    era_start: Optional[int] = None,
    era_end: Optional[int] = None,
) -> ListeningProfile:
    """Reduce raw scrobbles into per-artist play weights and names.

    Two independent, optional temporal shapings (EXP-06 — Temporal taste
    profiles), applied in this order:

    1. **Era window.** If ``era_start``/``era_end`` (unix seconds) are given,
       scrobbles outside that *inclusive* ``[era_start, era_end]`` window are
       dropped before anything is counted — a "my 2019 self" profile.
    2. **Recency decay.** If ``half_life_days`` is given, each surviving play
       is weighted ``0.5 ** ((now_ts - s.ts) / (half_life_days * 86400))``
       instead of a flat ``1``, so a play exactly one half-life before
       ``now_ts`` counts half as much as a play at ``now_ts``. ``now_ts``
       defaults to the max timestamp among the (era-filtered) scrobbles —
       *not* the wall clock — so the profile is reproducible from the same
       scrobble list alone.

    With both ``None`` (the default), this reproduces the exact play counts
    of the original flat-count profile, as floats (``10.0 == 10``) — see
    :class:`~pipeline.models.ListeningProfile`.
    """
    windowed = [
        s
        for s in scrobbles
        if (era_start is None or s.ts >= era_start) and (era_end is None or s.ts <= era_end)
    ]
    effective_now = now_ts if now_ts is not None else max((s.ts for s in windowed), default=0)

    play_counts: dict[str, float] = {}
    artist_names: dict[str, str] = {}
    for s in windowed:
        key = s.artist_id or s.artist_name
        if not key:
            continue
        weight = 1.0
        if half_life_days is not None:
            weight = 0.5 ** ((effective_now - s.ts) / (half_life_days * 86400))
        play_counts[key] = play_counts.get(key, 0.0) + weight
        artist_names.setdefault(key, s.artist_name)
    return ListeningProfile(
        username=username,
        play_counts=play_counts,
        artist_names=artist_names,
        tags={},  # filled in during enrichment
    )


def enrich_artist(
    artist_id: str,
    name: str,
    source: ScrobbleSource,
    enricher: EnrichmentSource,
    *,
    listeners: int = 0,
    playcount: int = 0,
) -> Artist:
    """Build a fully enriched :class:`Artist` with sourced identity + composition."""
    tags = source.artist_tags(artist_id)
    identity = resolve_identity(enricher.gender_evidence(artist_id))
    fronts, comp_evidence = enricher.composition_evidence(artist_id)
    composition = resolve_composition(fronts, comp_evidence)
    return Artist(
        artist_id=artist_id,
        name=name,
        tags=tags,
        identity=identity,
        composition=composition,
        listeners=listeners,
        playcount=playcount,
    )


def ingest(
    username: str,
    source: ScrobbleSource,
    enricher: EnrichmentSource,
    *,
    cache: Optional[Cache] = None,
    fetched_at: str = "1970-01-01",
    limit: int = 200,
) -> tuple[ListeningProfile, dict[str, Artist]]:
    """Run the full ingest. Returns the listening profile and an enriched catalog.

    When a ``cache`` is supplied, scrobbles and enriched artists are persisted
    with the given ``fetched_at`` lineage timestamp.
    """
    scrobbles = source.recent_scrobbles(username, limit=limit)
    if cache is not None:
        cache.put_scrobbles(username, scrobbles)
    profile = build_profile(username, scrobbles)

    catalog: dict[str, Artist] = {}
    tags_by_artist: dict[str, tuple[str, ...]] = {}
    for artist_id, name in profile.artist_names.items():
        artist = enrich_artist(
            artist_id,
            name,
            source,
            enricher,
            playcount=int(profile.play_counts.get(artist_id, 0)),
        )
        catalog[artist_id] = artist
        tags_by_artist[artist_id] = artist.tags
        if cache is not None:
            cache.put_artist(artist, fetched_at=fetched_at)

    # Re-emit the profile with tags now known (frozen dataclass → rebuild).
    profile = ListeningProfile(
        username=profile.username,
        play_counts=profile.play_counts,
        artist_names=profile.artist_names,
        tags=tags_by_artist,
    )
    return profile, catalog
