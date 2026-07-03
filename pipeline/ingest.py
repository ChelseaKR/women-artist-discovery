"""Ingest orchestration: username -> stored listening profile + enriched catalog.

Ties together the :class:`~pipeline.lastfm.ScrobbleSource`, the
:class:`~pipeline.enrich.EnrichmentSource`, the identity resolver, and the local
:class:`~pipeline.cache.Cache`. The result is:

* a :class:`~pipeline.models.ListeningProfile` (per-artist play weights + tags), and
* a catalog of enriched :class:`~pipeline.models.Artist` objects with *sourced*
  identity + composition (defaulting to unknown), each cached with a fetch date.

FIX-12 (operability): every stage logs its start, elapsed time, and a short
result summary via ``wad.ingest`` (see :mod:`pipeline.logconfig`), and a
live-mode failure is logged with the stage + source it happened in before the
exception is re-raised — never swallowed.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from pipeline.cache import Cache
from pipeline.enrich import EnrichmentSource
from pipeline.identity import resolve_composition, resolve_identity
from pipeline.lastfm import ScrobbleSource
from pipeline.models import Artist, ListeningProfile, Scrobble

log = logging.getLogger("wad.ingest")


def build_profile(username: str, scrobbles: list[Scrobble]) -> ListeningProfile:
    """Reduce raw scrobbles into per-artist play counts and names."""
    play_counts: dict[str, int] = {}
    artist_names: dict[str, str] = {}
    for s in scrobbles:
        key = s.artist_id or s.artist_name
        if not key:
            continue
        play_counts[key] = play_counts.get(key, 0) + 1
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
    ingest_start = time.monotonic()
    log.info("stage=ingest event=start username=%s limit=%d", username, limit)

    stage_start = time.monotonic()
    try:
        scrobbles = source.recent_scrobbles(username, limit=limit)
    except Exception:
        log.exception(
            "stage=fetch_scrobbles event=failed username=%s source=%s",
            username,
            type(source).__name__,
        )
        raise
    log.info(
        "stage=fetch_scrobbles event=end elapsed=%.3fs count=%d",
        time.monotonic() - stage_start,
        len(scrobbles),
    )

    if cache is not None:
        stage_start = time.monotonic()
        cache.put_scrobbles(username, scrobbles)
        log.info("stage=cache_scrobbles event=end elapsed=%.3fs", time.monotonic() - stage_start)
    profile = build_profile(username, scrobbles)

    stage_start = time.monotonic()
    catalog: dict[str, Artist] = {}
    tags_by_artist: dict[str, tuple[str, ...]] = {}
    for artist_id, name in profile.artist_names.items():
        try:
            artist = enrich_artist(
                artist_id,
                name,
                source,
                enricher,
                playcount=profile.play_counts.get(artist_id, 0),
            )
        except Exception:
            log.exception(
                "stage=enrich event=failed artist_id=%s enricher=%s",
                artist_id,
                type(enricher).__name__,
            )
            raise
        catalog[artist_id] = artist
        tags_by_artist[artist_id] = artist.tags
        if cache is not None:
            cache.put_artist(artist, fetched_at=fetched_at)
    log.info(
        "stage=enrich event=end elapsed=%.3fs count=%d",
        time.monotonic() - stage_start,
        len(catalog),
    )

    # Re-emit the profile with tags now known (frozen dataclass → rebuild).
    profile = ListeningProfile(
        username=profile.username,
        play_counts=profile.play_counts,
        artist_names=profile.artist_names,
        tags=tags_by_artist,
    )
    log.info(
        "stage=ingest event=end elapsed=%.3fs username=%s artists=%d",
        time.monotonic() - ingest_start,
        username,
        len(catalog),
    )
    return profile, catalog
