"""Playlist export: turn recommendations into a Spotify playlist or a portable file.

This is the project's **only** user-initiated outbound data path beyond the
Last.fm/enrichment fetch. It is opt-in, runs nothing on import, and reads every
credential from the environment (never hard-coded). The graceful fallbacks
(plain text / CSV / M3U / JSPF) need no account at all.
"""
