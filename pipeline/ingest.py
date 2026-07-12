"""Ingest orchestration: username -> stored listening profile + enriched catalog.

Ties together the :class:`~pipeline.lastfm.ScrobbleSource`, the
:class:`~pipeline.enrich.EnrichmentSource`, the identity resolver, and the local
:class:`~pipeline.cache.Cache`. The result is:

* a :class:`~pipeline.models.ListeningProfile` (per-artist play weights + tags), and
* a catalog of enriched :class:`~pipeline.models.Artist` objects with *sourced*
  identity + composition (defaulting to unknown), each cached with a fetch date.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pipeline.cache import Cache
from pipeline.enrich import EnrichmentSource
from pipeline.identity import resolve_composition, resolve_identity
from pipeline.lastfm import ScrobbleSource
from pipeline.models import Artist, IdentityLabel, ListeningProfile, Scrobble


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
    cache: Optional[Cache] = None,
) -> Artist:
    """Build a fully enriched :class:`Artist` with sourced identity + composition.

    When ``cache`` is supplied, any locally-entered corrections (FIX-10) for
    this artist are fed into the resolver alongside the enricher's evidence.
    A correction is itself an ``ARTIST_STATEMENT`` — the resolver's existing
    priority order (``ARTIST_STATEMENT`` highest) is what lets it win, with no
    special-casing in :func:`~pipeline.identity.resolve_identity`.
    """
    tags = source.artist_tags(artist_id)
    evidence = list(enricher.gender_evidence(artist_id))
    if cache is not None:
        evidence.extend(cache.get_corrections(artist_id))
    identity = resolve_identity(evidence)
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
            playcount=profile.play_counts.get(artist_id, 0),
            cache=cache,
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


@dataclass(frozen=True)
class LabelChange:
    """An identity label that changed on re-enrichment — the correction ledger row."""

    artist_id: str
    old: IdentityLabel
    new: IdentityLabel


def refresh_catalog(
    cache: Cache, catalog: dict[str, Artist], *, fetched_at: str
) -> list[LabelChange]:
    """Re-persist an enriched catalog, reporting identity-label changes (FIX-04).

    The correction path (ROADMAP §9 / RR-2): each freshly-enriched artist is compared
    against the label the cache currently holds; every changed identity label is
    reported with its before/after, then the new label is written. Artists absent
    from the cache are stored without being reported as "changes".
    """
    changes: list[LabelChange] = []
    for artist_id, artist in catalog.items():
        cached = cache.get_artist(artist_id)
        if cached is not None and cached.identity != artist.identity:
            changes.append(LabelChange(artist_id, cached.identity, artist.identity))
        cache.put_artist(artist, fetched_at=fetched_at)
    return changes
