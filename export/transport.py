"""The injectable HTTP surface shared by every live playlist-export provider.

Hoisted out of :mod:`export.spotify` so a second provider (ListenBrainz) can
reuse the exact same :class:`HttpTransport` Protocol and :class:`HttpResponse`
value type without importing provider-specific code. ``export.spotify``
re-exports these names so its public API is unchanged.

Only :class:`RequestsTransport` opens a socket; everything else is exercised
offline with a fake transport in tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class HttpResponse:
    """A minimal HTTP response: a status code and the parsed JSON body."""

    status: int
    body: dict[str, Any]

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@runtime_checkable
class HttpTransport(Protocol):
    """The tiny HTTP surface a provider client needs. Injectable for testing."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        data: Optional[Mapping[str, str]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
    ) -> HttpResponse: ...


class RequestsTransport:  # pragma: no cover - live network path, verified manually
    """The one live transport. Imports ``requests`` lazily, like the Last.fm client."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        data: Optional[Mapping[str, str]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
    ) -> HttpResponse:
        import requests

        resp = requests.request(
            method,
            url,
            headers=dict(headers or {}),
            data=dict(data) if data is not None else None,
            json=dict(json_body) if json_body is not None else None,
            timeout=self.timeout,
        )
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = {}
        return HttpResponse(status=resp.status_code, body=body if isinstance(body, dict) else {})
