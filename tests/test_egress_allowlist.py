"""R9: the outbound-network surface is *enumerable* — exactly two egress points.

The project's privacy promise ("nothing leaves your machine except a user-initiated
export") is only as strong as it is *checkable*. This test names the complete
allow-list of files permitted to open a socket and fails if any other module in
the source tree reaches the network — so a new egress path cannot be added silently,
and the "no misusable database" guarantee stays enumerable rather than aspirational.
"""

from __future__ import annotations

from pathlib import Path

import pipeline

# The repo root holds the four first-party source packages.
_REPO_ROOT = Path(pipeline.__file__).resolve().parent.parent
_PACKAGES = ("pipeline", "recommender", "export", "app")

# Tokens that indicate a module can itself open a network connection.
NETWORK_TOKENS = (
    "import requests",
    "requests.get",
    "requests.post",
    "requests.request",
    "urllib.request",
    "http.client",
    "import socket",
    "socket.socket",
)

# The COMPLETE allow-list of outbound egress points — named, not discovered.
# Anything else reaching the network is a regression.
ALLOWED_EGRESS: dict[str, str] = {
    "pipeline/lastfm.py": "LastfmClient._get — Last.fm ingest/enrichment fetch (cached)",
    "export/spotify.py": "RequestsTransport.request — user-initiated Spotify export",
}


def _source_files() -> list[Path]:
    files: list[Path] = []
    for package in _PACKAGES:
        files.extend((_REPO_ROOT / package).rglob("*.py"))
    return files


def _reaches_network(text: str) -> bool:
    return any(token in text for token in NETWORK_TOKENS)


def test_exactly_two_egress_points_are_allow_listed() -> None:
    assert len(ALLOWED_EGRESS) == 2  # Last.fm fetch + Spotify export — and nothing more


def test_no_module_reaches_the_network_outside_the_allow_list() -> None:
    offenders: list[str] = []
    for path in _source_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if _reaches_network(path.read_text(encoding="utf-8")) and rel not in ALLOWED_EGRESS:
            offenders.append(rel)
    assert not offenders, f"network egress outside the allow-list: {offenders}"


def test_allow_listed_files_actually_carry_an_egress_path() -> None:
    """The allow-list must not go stale: each named file still opens the network."""
    for rel in ALLOWED_EGRESS:
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        assert _reaches_network(text), f"{rel} is allow-listed but no longer reaches the network"
