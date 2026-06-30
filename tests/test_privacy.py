"""Privacy audit §C: no telemetry, and network egress confined to one place.

These are source-level guarantees (DPIA: data-minimisation + purpose-limitation):
the listening data is local-first, so the core must not import analytics SDKs and
must not open network connections anywhere except the explicit Last.fm/enrichment
client paths.
"""

from __future__ import annotations

from pathlib import Path

import pipeline
import recommender

TELEMETRY_TOKENS = (
    "mixpanel",
    "segment.analytics",
    "amplitude",
    "posthog",
    "sentry_sdk",
    "datadog",
    "google.analytics",
    "googleanalytics",
)

# Network may only be reached from these modules (the live API clients).
NETWORK_ALLOWED = {"lastfm.py"}
NETWORK_TOKENS = ("import requests", "urllib.request", "http.client", "import socket")


def _core_files() -> list[Path]:
    roots = [Path(pipeline.__file__).parent, Path(recommender.__file__).parent]
    return [p for root in roots for p in root.rglob("*.py")]


def test_core_imports_no_telemetry_sdk() -> None:
    for path in _core_files():
        text = path.read_text(encoding="utf-8").lower()
        for token in TELEMETRY_TOKENS:
            assert token not in text, f"{path.name} references telemetry: {token}"


def test_network_access_is_confined_to_api_clients() -> None:
    for path in _core_files():
        if path.name in NETWORK_ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        for token in NETWORK_TOKENS:
            assert token not in text, f"{path.name} opens network outside an API client: {token}"


def test_cache_uses_only_stdlib_sqlite() -> None:
    cache_src = (Path(pipeline.__file__).parent / "cache.py").read_text(encoding="utf-8")
    assert "import sqlite3" in cache_src
    for token in ("requests", "boto3", "psycopg", "pymongo", "redis"):
        assert token not in cache_src
