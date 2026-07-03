"""ListenBrainz playlist export via a static user token.

Design mirrors :mod:`export.spotify`: the network is reached through the same
injectable :class:`~export.transport.HttpTransport` Protocol, so the whole
flow is unit-tested offline with a fake transport, and the one live
implementation (:class:`~export.transport.RequestsTransport`) is the only
thing that actually opens a socket. Credentials come from the environment
only — there are no defaults and nothing is ever hard-coded.

Unlike Spotify, ListenBrainz authenticates with a single static user token —
no OAuth dance, no client secret, no redirect URI — so this client is a lot
smaller than :mod:`export.spotify`: build credentials, call
:func:`export_recommendations`, done.

To run live you need a ListenBrainz account and this env var::

    WAD_LISTENBRAINZ_TOKEN=...  (from https://listenbrainz.org/settings/)

The playlist body is the project's own JSPF document
(:func:`export.tracklist._jspf_document`) plus the ListenBrainz
public/private extension — the same structure the credential-free JSPF
fallback writes to disk, just POSTed instead.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Optional

from pipeline.models import Recommendation

from export.models import ExportError, PlaylistExport
from export.tracklist import _jspf_document, recommendations_to_tracks
from export.transport import HttpTransport

__all__ = [
    "API_ROOT",
    "ListenBrainzCredentials",
    "export_recommendations",
]

API_ROOT = "https://api.listenbrainz.org/1"
#: The JSPF extension namespace ListenBrainz reads the public/private flag from.
_PLAYLIST_EXTENSION = "https://musicbrainz.org/doc/jspf#playlist"


@dataclass(frozen=True)
class ListenBrainzCredentials:
    """A ListenBrainz user token, read from the environment — never hard-coded."""

    token: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> ListenBrainzCredentials:
        """Build credentials from ``env``; raise :class:`ExportError` if missing."""
        token = env.get("WAD_LISTENBRAINZ_TOKEN", "").strip()
        if not token:
            raise ExportError("missing ListenBrainz credentials in env: WAD_LISTENBRAINZ_TOKEN")
        return cls(token=token)

    def _auth_header(self) -> str:
        return f"Token {self.token}"


def export_recommendations(
    recs: Sequence[Recommendation],
    credentials: ListenBrainzCredentials,
    transport: HttpTransport,
    *,
    username: str = "you",
    playlist_name: Optional[str] = None,
    public: bool = False,
) -> PlaylistExport:
    """Create a ListenBrainz playlist from recommendations and report the outcome.

    Every recommended artist becomes one JSPF track (identical shape to the
    credential-free JSPF fallback); the values-aware ordering of ``recs`` is
    preserved. ListenBrainz resolves tracks server-side from the submitted
    metadata, so — unlike Spotify — there is no separate search step here and
    every submitted track counts as matched.
    """
    tracks = recommendations_to_tracks(recs)
    if not tracks:
        raise ExportError("nothing to export: the recommendation set is empty")

    name = playlist_name or f"Women-Artist Discovery — {username}"
    document = _jspf_document(tracks, name)
    document["playlist"]["extension"] = {_PLAYLIST_EXTENSION: {"public": public}}

    resp = transport.request(
        "POST",
        f"{API_ROOT}/playlist/create",
        headers={
            "Authorization": credentials._auth_header(),
            "Content-Type": "application/json",
        },
        json_body=document,
    )
    if not resp.ok:
        raise ExportError(f"ListenBrainz playlist create failed (HTTP {resp.status})")

    mbid = str(resp.body.get("playlist_mbid", "")).strip()
    if not mbid:
        raise ExportError("ListenBrainz did not return a playlist_mbid")

    return PlaylistExport(
        provider="listenbrainz",
        playlist_name=name,
        track_count=len(tracks),
        matched_count=len(tracks),
        playlist_id=mbid,
        playlist_url=f"https://listenbrainz.org/playlist/{mbid}",
    )
