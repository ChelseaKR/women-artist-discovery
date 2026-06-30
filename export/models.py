"""Provider-agnostic value types for playlist export."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


class ExportError(Exception):
    """Raised when an export cannot be completed (auth, network, or API error)."""


class ExportFormat(enum.Enum):
    """The credential-free fallback formats. Every one is a portable local file."""

    TEXT = "txt"
    CSV = "csv"
    M3U = "m3u8"
    JSPF = "jspf"  # JSON playlist (XSPF's JSON sibling)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PlaylistTrack:
    """One entry in an export.

    Recommendations are *artists*, so an entry names the artist and carries the
    ``query`` a streaming provider would search to find a representative track.
    ``title`` stays ``None`` offline (we never invent a specific track); a
    provider search fills ``provider_uri``/``provider_url`` when it resolves one.
    ``why`` is a short, honest reason carried into the export for transparency.
    """

    artist_name: str
    artist_id: str
    rank: int = 0
    title: Optional[str] = None
    query: str = ""
    why: str = ""
    provider_uri: Optional[str] = None
    provider_url: Optional[str] = None

    @property
    def resolved(self) -> bool:
        """True once a provider has matched this entry to a concrete track."""
        return self.provider_uri is not None


@dataclass(frozen=True)
class PlaylistExport:
    """The result of an export — what happened, where it went, what didn't match."""

    provider: str
    playlist_name: str
    track_count: int
    matched_count: int = 0
    playlist_url: Optional[str] = None
    playlist_id: Optional[str] = None
    unmatched: tuple[str, ...] = field(default_factory=tuple)

    @property
    def fully_matched(self) -> bool:
        return self.track_count > 0 and self.matched_count == self.track_count
