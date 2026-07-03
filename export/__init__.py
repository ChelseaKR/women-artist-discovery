"""Playlist export: turn recommendations into a live playlist or a portable file.

This is the project's **only** user-initiated outbound data path beyond the
Last.fm/enrichment fetch. It is opt-in, runs nothing on import, and reads every
credential from the environment (never hard-coded). The graceful fallbacks
(plain text / CSV / M3U / JSPF) need no account at all.

Two live providers ship behind the same injectable-transport pattern and the
same :class:`~export.models.PlaylistExport` result type — Spotify
(:mod:`export.spotify`, OAuth) and ListenBrainz (:mod:`export.listenbrainz`,
static user token) — proving this package is provider-agnostic rather than
Spotify-specific. See :mod:`export.registry` for the lookup table naming them.
"""
