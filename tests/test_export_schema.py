"""R9: no identity field may appear in any export format.

An export is the project's one egress. To stay true to "never build a misusable
musician-identity database," what leaves must be *only* artist names + a non-identity
reason — never a gender, a basis, or a provenance citation. These tests assert that
structurally (the schema of every format) and by content (the rendered bytes), using
the demo world, which deliberately contains women, nonbinary, and female-fronted
artists — so any leak would show.
"""

from __future__ import annotations

import dataclasses
import json

from export.models import ExportFormat, PlaylistTrack
from export.tracklist import recommendations_to_tracks, render, to_csv, to_jspf
from recommender.hybrid import recommend

# Field/column/key names that would mean identity is being carried.
FORBIDDEN_FIELDS = frozenset(
    {
        "gender",
        "identity",
        "identity_basis",
        "basis",
        "sex",
        "pronoun",
        "pronouns",
        "self_identified",
        "self-identified",
        "female_fronted",
        "female-fronted",
        "provenance",
        "source",
        "sources",
        "wikidata",
        "musicbrainz",
        "p21",
    }
)

# Identity vocabulary that must never appear in the rendered bytes of any export.
FORBIDDEN_CONTENT_TOKENS = (
    "woman",
    "nonbinary",
    "non-binary",
    "self-identified",
    "female-fronted",
    "band-composition",
    "wikidata",
    "musicbrainz",
    "p21",
    "gender",
    "identity:",
)


def _demo_tracks(profile, catalog, source):
    # Full strength + a wide k, so every identity in the demo world is in scope.
    recs = recommend(profile, catalog, source, k=99, lens_strength=1.0)
    return recommendations_to_tracks(recs)


def test_playlist_track_schema_has_no_identity_field() -> None:
    field_names = {f.name.lower() for f in dataclasses.fields(PlaylistTrack)}
    leaked = field_names & FORBIDDEN_FIELDS
    assert not leaked, f"export track schema carries identity fields: {leaked}"


def test_csv_header_has_no_identity_column(profile, catalog, source) -> None:
    header = to_csv(_demo_tracks(profile, catalog, source)).splitlines()[0]
    columns = {c.strip().lower() for c in header.split(",")}
    assert not (columns & FORBIDDEN_FIELDS), (
        f"CSV header leaks identity: {columns & FORBIDDEN_FIELDS}"
    )


def test_jspf_track_keys_have_no_identity_field(profile, catalog, source) -> None:
    doc = json.loads(to_jspf(_demo_tracks(profile, catalog, source)))
    for track in doc["playlist"]["track"]:
        keys = {k.lower() for k in track}
        assert not (keys & FORBIDDEN_FIELDS), (
            f"JSPF track leaks identity: {keys & FORBIDDEN_FIELDS}"
        )


def test_no_export_format_leaks_identity_vocabulary(profile, catalog, source) -> None:
    tracks = _demo_tracks(profile, catalog, source)
    assert tracks  # sanity: the demo produced something to inspect
    for fmt in ExportFormat:
        rendered = render(tracks, fmt).lower()
        assert "mitski" in rendered  # the export is non-empty / really contains artists
        for token in FORBIDDEN_CONTENT_TOKENS:
            assert token not in rendered, f"{fmt} export leaks identity token {token!r}"
