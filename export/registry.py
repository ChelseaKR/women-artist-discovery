"""A small provider registry proving ``export/`` is provider-agnostic.

Every live provider ends at the same :class:`~export.models.PlaylistExport`
result type via the same injectable-transport pattern
(:mod:`export.transport`); this module is just the lookup table naming them,
so callers (the dashboard, a future CLI) can iterate providers instead of
hard-coding "Spotify" everywhere. Importing this module opens no connections
and reads no credentials — it only references the ``export_recommendations``
functions, which themselves take credentials/transport as arguments.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from export import listenbrainz, spotify

#: Signature every provider's ``export_recommendations`` conforms to, modulo
#: provider-specific keyword args (client vs. credentials+transport) — callers
#: use ``PROVIDERS[name].export_fn`` with knowledge of that provider's shape.
ExportFn = Callable[..., Any]


@dataclass(frozen=True)
class ProviderInfo:
    """One entry in the provider registry."""

    name: str
    export_fn: ExportFn
    requires_auth: bool
    #: A one-line, human-readable statement of what leaves the machine and
    #: when — the egress claim this provider makes, kept next to the code it
    #: describes so it can't silently drift from ``docs/audits/privacy-notes.md``.
    egress_summary: str


PROVIDERS: dict[str, ProviderInfo] = {
    "spotify": ProviderInfo(
        name="Spotify",
        export_fn=spotify.export_recommendations,
        requires_auth=True,
        egress_summary=(
            "OAuth access token + recommended artist names, sent to "
            "api.spotify.com only when the user clicks connect/export."
        ),
    ),
    "listenbrainz": ProviderInfo(
        name="ListenBrainz",
        export_fn=listenbrainz.export_recommendations,
        requires_auth=True,
        egress_summary=(
            "Static user token + a JSPF playlist of recommended artist names, "
            "sent to api.listenbrainz.org only when the user clicks export."
        ),
    ),
}
