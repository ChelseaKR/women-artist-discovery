"""ListenBrainz playlist export, and the provider registry proving ``export/``
is provider-agnostic.

Mirrors ``tests/test_export.py``'s Spotify coverage: the live network is never
touched — a :class:`FakeTransport` stands in for HTTP.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Optional

import pytest
from export import listenbrainz as lb
from export.listenbrainz import (
    ListenBrainzCredentials,
    export_recommendations,
)
from export.models import ExportError, PlaylistExport
from export.registry import PROVIDERS, ProviderInfo
from export.transport import HttpResponse, HttpTransport
from recommender.hybrid import recommend

_ENV = {"WAD_LISTENBRAINZ_TOKEN": "lb-token-123"}


class FakeTransport:
    """An in-memory HTTP double routing the one ListenBrainz endpoint we use."""

    def __init__(self, status: int = 200, mbid: str = "mbid-abc-123") -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = status
        self.mbid = mbid

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        data: Optional[Mapping[str, str]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
    ) -> HttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "json": dict(json_body) if json_body else None,
            }
        )
        if url.endswith("/playlist/create"):
            body: dict[str, Any] = {}
            if self.status < 300 and self.mbid:
                body = {"playlist_mbid": self.mbid}
            return HttpResponse(self.status, body)
        return HttpResponse(404, {})  # pragma: no cover - defensive default


# --- Credentials --------------------------------------------------------------


def test_credentials_from_env_reads_token() -> None:
    creds = ListenBrainzCredentials.from_env(_ENV)
    assert creds.token == "lb-token-123"


def test_credentials_from_env_raises_when_missing() -> None:
    with pytest.raises(ExportError, match="WAD_LISTENBRAINZ_TOKEN"):
        ListenBrainzCredentials.from_env({})


# --- export_recommendations ---------------------------------------------------


def test_export_recommendations_posts_wellformed_jspf_with_token_auth(
    profile, catalog, source
) -> None:
    recs = recommend(profile, catalog, source, k=4, lens_strength=0.5)
    creds = ListenBrainzCredentials.from_env(_ENV)
    transport = FakeTransport()

    export_recommendations(recs, creds, transport, username="demo")

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == f"{lb.API_ROOT}/playlist/create"
    assert call["headers"]["Authorization"] == "Token lb-token-123"
    assert call["headers"]["Content-Type"] == "application/json"

    body = call["json"]
    assert body is not None
    playlist = body["playlist"]
    assert playlist["title"]
    assert len(playlist["track"]) == len(recs)
    assert playlist["track"][0]["creator"] == recs[0].artist.name
    # It must round-trip through plain JSON (a real POST body).
    json.dumps(body)


def test_export_recommendations_sets_public_extension_flag(profile, catalog, source) -> None:
    recs = recommend(profile, catalog, source, k=2, lens_strength=0.5)
    creds = ListenBrainzCredentials.from_env(_ENV)
    transport = FakeTransport()

    export_recommendations(recs, creds, transport, public=True)

    ext = transport.calls[0]["json"]["playlist"]["extension"]
    assert ext["https://musicbrainz.org/doc/jspf#playlist"]["public"] is True


def test_export_recommendations_defaults_to_private(profile, catalog, source) -> None:
    recs = recommend(profile, catalog, source, k=2, lens_strength=0.5)
    creds = ListenBrainzCredentials.from_env(_ENV)
    transport = FakeTransport()

    export_recommendations(recs, creds, transport)

    ext = transport.calls[0]["json"]["playlist"]["extension"]
    assert ext["https://musicbrainz.org/doc/jspf#playlist"]["public"] is False


def test_export_recommendations_parses_mbid_into_playlist_export(profile, catalog, source) -> None:
    recs = recommend(profile, catalog, source, k=3, lens_strength=0.5)
    creds = ListenBrainzCredentials.from_env(_ENV)
    transport = FakeTransport(mbid="mbid-xyz")

    result = export_recommendations(recs, creds, transport, username="chelsea")

    assert isinstance(result, PlaylistExport)
    assert result.provider == "listenbrainz"
    assert result.track_count == len(recs)
    assert result.matched_count == len(recs)
    assert result.fully_matched
    assert result.playlist_id == "mbid-xyz"
    assert result.playlist_url == "https://listenbrainz.org/playlist/mbid-xyz"
    assert "chelsea" in result.playlist_name


def test_export_recommendations_raises_on_non_2xx(profile, catalog, source) -> None:
    recs = recommend(profile, catalog, source, k=2, lens_strength=0.5)
    creds = ListenBrainzCredentials.from_env(_ENV)
    transport = FakeTransport(status=401)

    with pytest.raises(ExportError, match="failed"):
        export_recommendations(recs, creds, transport)


def test_export_recommendations_raises_when_mbid_missing(profile, catalog, source) -> None:
    recs = recommend(profile, catalog, source, k=2, lens_strength=0.5)
    creds = ListenBrainzCredentials.from_env(_ENV)
    transport = FakeTransport(mbid="")

    with pytest.raises(ExportError, match="playlist_mbid"):
        export_recommendations(recs, creds, transport)


def test_export_recommendations_empty_raises() -> None:
    creds = ListenBrainzCredentials.from_env(_ENV)
    with pytest.raises(ExportError, match="empty"):
        export_recommendations([], creds, FakeTransport())


def test_transport_is_an_http_transport_consumer() -> None:
    assert isinstance(FakeTransport(), HttpTransport)  # runtime_checkable Protocol


# --- Provider registry ---------------------------------------------------------


def test_registry_lists_both_providers() -> None:
    assert set(PROVIDERS) == {"spotify", "listenbrainz"}
    for info in PROVIDERS.values():
        assert isinstance(info, ProviderInfo)
        assert info.requires_auth is True
        assert callable(info.export_fn)
        assert info.egress_summary


def test_registry_listenbrainz_entry_points_at_the_real_function() -> None:
    assert PROVIDERS["listenbrainz"].export_fn is export_recommendations
    assert PROVIDERS["listenbrainz"].name == "ListenBrainz"


def test_registry_import_opens_no_network() -> None:
    # Importing export.registry must not read env vars or open a connection —
    # asserted here by the fact that this test needs no credentials at all
    # and the module-level PROVIDERS dict is already fully built above.
    from export import registry

    assert "spotify" in registry.PROVIDERS
