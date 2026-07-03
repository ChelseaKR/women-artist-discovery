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
from pipeline.models import Artist, ListeningProfile, Scrobble, Source


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


@dataclass(frozen=True)
class IdentityLabelChange:
    """One identity-source change detected by re-enriching a cached artist.

    ``wad refresh`` re-runs enrichment for every cached artist and reports one
    of these whenever a source *kind already on file* now asserts a different
    value or carries a newer ``retrieved_at`` — the observable signal that an
    upstream edit (e.g. a Wikidata P21 correction) has landed. This is the
    minimal shape EXP-05's :mod:`pipeline.corrections` needs to reconcile a
    locally-filed pending correction against; a fuller source-conflict ledger
    is out of scope here (see roadmap FIX-10).
    """

    artist_id: str
    source_kind: str
    old_value: str
    new_value: str
    retrieved_at: str


def _identity_sources(artist: Artist) -> tuple[Source, ...]:
    sources: tuple[Source, ...] = artist.identity.sources
    if artist.composition is not None:
        sources = sources + artist.composition.sources
    return sources


def diff_identity_sources(old: Artist, new: Artist) -> list[IdentityLabelChange]:
    """Compare two enrichment passes for the same artist; report per-source changes.

    Only source kinds present in *both* passes are compared — a kind that
    newly appears or disappears is a bigger event (a full source-conflict view
    is FIX-10's scope) than the narrow "this citation's value moved" signal
    ``reconcile()`` needs.
    """
    old_by_kind = {s.kind: s for s in _identity_sources(old)}
    new_by_kind = {s.kind: s for s in _identity_sources(new)}
    changes: list[IdentityLabelChange] = []
    for kind, new_src in new_by_kind.items():
        old_src = old_by_kind.get(kind)
        if old_src is None:
            continue
        if old_src.detail != new_src.detail or old_src.retrieved_at != new_src.retrieved_at:
            changes.append(
                IdentityLabelChange(
                    artist_id=new.artist_id,
                    source_kind=str(kind),
                    old_value=old_src.detail,
                    new_value=new_src.detail,
                    retrieved_at=new_src.retrieved_at,
                )
            )
    return changes


def refresh_catalog(
    cache: Cache,
    source: ScrobbleSource,
    enricher: EnrichmentSource,
    *,
    fetched_at: str,
) -> list[IdentityLabelChange]:
    """Re-enrich every cached artist; persist the refresh and report changes.

    This is ``wad refresh``'s core: each cached artist is re-resolved through
    the same :func:`enrich_artist` path ingest uses, the cache row is updated
    with the new lineage timestamp, and any identity-source change is
    reported so the caller (the CLI) can reconcile it against pending local
    corrections (:mod:`pipeline.corrections`).
    """
    changes: list[IdentityLabelChange] = []
    for artist_id in cache.list_artist_ids():
        old = cache.get_artist(artist_id)
        if old is None:  # pragma: no cover - defensive; id just came from this cache
            continue
        refreshed = enrich_artist(
            artist_id,
            old.name,
            source,
            enricher,
            listeners=old.listeners,
            playcount=old.playcount,
        )
        changes.extend(diff_identity_sources(old, refreshed))
        cache.put_artist(refreshed, fetched_at=fetched_at)
    return changes


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
