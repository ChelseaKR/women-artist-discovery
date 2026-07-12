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
from typing import Optional, overload

from pipeline.cache import Cache
from pipeline.enrich import EnrichmentSource
from pipeline.identity import resolve_composition, resolve_identity
from pipeline.lastfm import ScrobbleSource
from pipeline.models import Artist, IdentityLabel, ListeningProfile, Scrobble, Source


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

    When a ``cache`` is supplied, ingest is paginated and incremental (FIX-02):
    only scrobbles newer than the cache's watermark (``Cache.last_synced_ts``)
    are fetched, merged into the cache (idempotently — refetching the same
    range is harmless since only ``ts > since`` is ever requested), and the
    listening profile is built from the *full* stored history so play counts
    reflect everything synced so far, not just this run's delta. Enriched
    artists are persisted with the given ``fetched_at`` lineage timestamp.

    Without a ``cache``, ingest is a single-page snapshot, as before.
    """
    if cache is not None:
        since = cache.last_synced_ts(username)
        fetched = source.scrobbles_since(username, since_ts=since, page_size=limit)
        cache.put_scrobbles(username, fetched)
        scrobbles = cache.get_scrobbles(username)
    else:
        scrobbles = source.recent_scrobbles(username, limit=limit)
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


@dataclass(frozen=True)
class IdentityLabelChange:
    """One cited source value/date change observed during re-enrichment."""

    artist_id: str
    source_kind: str
    old_value: str
    new_value: str
    retrieved_at: str


def _identity_sources(artist: Artist) -> tuple[Source, ...]:
    sources = artist.identity.sources
    if artist.composition is not None:
        sources += artist.composition.sources
    return sources


def diff_identity_sources(old: Artist, new: Artist) -> list[IdentityLabelChange]:
    """Report source values or retrieval dates that changed between passes."""
    return _diff_sources(old.artist_id, _identity_sources(old), _identity_sources(new))


def _diff_sources(
    artist_id: str, old_sources: tuple[Source, ...], new_sources: tuple[Source, ...]
) -> list[IdentityLabelChange]:
    old_by_kind = {source.kind: source for source in old_sources}
    changes: list[IdentityLabelChange] = []
    for new_source in new_sources:
        old_source = old_by_kind.get(new_source.kind)
        if old_source is None:
            continue
        if (
            old_source.detail != new_source.detail
            or old_source.retrieved_at != new_source.retrieved_at
        ):
            changes.append(
                IdentityLabelChange(
                    artist_id=artist_id,
                    source_kind=str(new_source.kind),
                    old_value=old_source.detail,
                    new_value=new_source.detail,
                    retrieved_at=new_source.retrieved_at,
                )
            )
    return changes


def diff_identity_labels(
    artist_id: str, old: IdentityLabel, new: IdentityLabel
) -> list[IdentityLabelChange]:
    """Source-level detail for a label-level cache refresh change."""
    return _diff_sources(artist_id, old.sources, new.sources)


@overload
def refresh_catalog(
    cache: Cache, catalog_or_source: dict[str, Artist], *, fetched_at: str
) -> list[LabelChange]: ...


@overload
def refresh_catalog(
    cache: Cache,
    catalog_or_source: ScrobbleSource,
    enricher: EnrichmentSource,
    *,
    fetched_at: str,
) -> list[IdentityLabelChange]: ...


def refresh_catalog(
    cache: Cache,
    catalog_or_source: dict[str, Artist] | ScrobbleSource,
    enricher: Optional[EnrichmentSource] = None,
    *,
    fetched_at: str,
) -> list[LabelChange] | list[IdentityLabelChange]:
    """Re-persist an enriched catalog, reporting identity-label changes (FIX-04).

    The correction path (ROADMAP §9 / RR-2): each freshly-enriched artist is compared
    against the label the cache currently holds; every changed identity label is
    reported with its before/after, then the new label is written. Artists absent
    from the cache are stored without being reported as "changes".
    """
    if isinstance(catalog_or_source, dict):
        label_changes: list[LabelChange] = []
        for artist_id, artist in catalog_or_source.items():
            cached = cache.get_artist(artist_id)
            if cached is not None and cached.identity != artist.identity:
                label_changes.append(LabelChange(artist_id, cached.identity, artist.identity))
            cache.put_artist(artist, fetched_at=fetched_at)
        return label_changes

    if enricher is None:
        raise TypeError("source refresh requires an EnrichmentSource")
    source_changes: list[IdentityLabelChange] = []
    for artist_id in cache.list_artist_ids():
        cached = cache.get_artist(artist_id)
        if cached is None:  # pragma: no cover - id came from the same cache
            continue
        refreshed = enrich_artist(
            artist_id,
            cached.name,
            catalog_or_source,
            enricher,
            listeners=cached.listeners,
            playcount=cached.playcount,
            cache=cache,
        )
        source_changes.extend(diff_identity_sources(cached, refreshed))
        cache.put_artist(refreshed, fetched_at=fetched_at)
    return source_changes
