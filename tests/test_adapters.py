"""Last.fm + enrichment parsers: shape validation, rate limiting, lineage."""

from __future__ import annotations

import pytest
from pipeline.enrich import (
    parse_discogs_lineup,
    parse_musicbrainz_gender,
    parse_wikidata_p21,
)
from pipeline.identity import resolve_identity
from pipeline.lastfm import (
    RateLimiter,
    parse_recent_tracks,
    parse_similar,
    parse_top_tags,
)
from pipeline.models import Gender, SourceKind


# --- rate limiter (compliance gate, deterministic via injected clock) --------
def test_rate_limiter_spaces_calls_by_min_interval() -> None:
    t = [0.0]
    slept: list[float] = []
    rl = RateLimiter(min_interval=0.25, clock=lambda: t[0], sleeper=lambda s: slept.append(s))
    rl.acquire()  # first call: no wait
    rl.acquire()  # immediately again: must wait ~0.25s
    assert slept and slept[0] == pytest.approx(0.25)


def test_rate_limiter_no_wait_when_enough_time_passed() -> None:
    t = [0.0]
    slept: list[float] = []
    rl = RateLimiter(min_interval=0.25, clock=lambda: t[0], sleeper=lambda s: slept.append(s))
    rl.acquire()
    t[0] = 1.0  # plenty of time elapsed
    rl.acquire()
    assert slept == []


# --- last.fm parsers ---------------------------------------------------------
def test_parse_recent_tracks_skips_now_playing() -> None:
    payload = {
        "recenttracks": {
            "track": [
                {"name": "Live", "artist": {"#text": "A"}, "@attr": {"nowplaying": "true"}},
                {"name": "T", "artist": {"#text": "A", "mbid": "m1"}, "date": {"uts": "100"}},
            ]
        }
    }
    out = parse_recent_tracks(payload)
    assert len(out) == 1
    assert out[0].artist_id == "m1" and out[0].ts == 100


def test_parse_recent_tracks_handles_single_object() -> None:
    payload = {
        "recenttracks": {"track": {"name": "T", "artist": {"#text": "A"}, "date": {"uts": "5"}}}
    }
    assert len(parse_recent_tracks(payload)) == 1


def test_parse_top_tags_lowercases_and_caps() -> None:
    payload = {"toptags": {"tag": [{"name": "Indie Rock"}, {"name": "Dream Pop"}]}}
    assert parse_top_tags(payload) == ("indie rock", "dream pop")


def test_parse_similar_clamps_match() -> None:
    payload = {
        "similarartists": {"artist": [{"name": "A", "match": "1.5"}, {"mbid": "m", "match": "x"}]}
    }
    out = dict(parse_similar(payload))
    assert out["A"] == 1.0 and out["m"] == 0.0


@pytest.mark.parametrize("parser", [parse_recent_tracks, parse_top_tags, parse_similar])
def test_lastfm_parsers_reject_non_object(parser) -> None:
    with pytest.raises(ValueError):
        parser(["not", "an", "object"])


def test_parse_recent_tracks_skips_malformed_attr_without_crashing() -> None:
    """A non-object '@attr' (malformed/untrusted payload) must be skipped, not crash."""
    payload = {
        "recenttracks": {
            "track": [
                {"name": "T", "artist": {"#text": "A"}, "date": {"uts": "1"}, "@attr": "oops"}
            ]
        }
    }
    out = parse_recent_tracks(payload)
    assert len(out) == 1 and out[0].ts == 1


def test_parse_recent_tracks_skips_non_object_artist_without_crashing() -> None:
    """Malformed artist rows are absent while valid siblings survive."""
    payload = {
        "recenttracks": {
            "track": [
                {"name": "bad-type", "artist": "Mitski", "date": {"uts": "1"}},
                {"name": "bad-empty", "artist": {}, "date": {"uts": "2"}},
                {
                    "name": "good",
                    "artist": {"#text": "Mitski", "mbid": "m1"},
                    "date": {"uts": "3"},
                },
            ]
        }
    }
    out = parse_recent_tracks(payload)
    assert len(out) == 1
    assert out[0].artist_id == "m1" and out[0].artist_name == "Mitski"
    assert out[0].track == "good" and out[0].ts == 3


def test_parse_recent_tracks_skips_non_numeric_timestamp_without_crashing() -> None:
    """A non-numeric 'uts' (malformed/untrusted payload) must be skipped, not crash."""
    payload = {
        "recenttracks": {
            "track": [
                {"name": "bad", "artist": {"#text": "A"}, "date": {"uts": "not-a-number"}},
                {"name": "good", "artist": {"#text": "B", "mbid": "m1"}, "date": {"uts": "100"}},
            ]
        }
    }
    out = parse_recent_tracks(payload)
    assert len(out) == 1
    assert out[0].artist_id == "m1" and out[0].ts == 100


# --- enrichment parsers (validation + provenance) ----------------------------
def test_musicbrainz_gender_valid_and_invalid() -> None:
    ev = parse_musicbrainz_gender({"gender": "Female"}, "mb://1", "2026-05-31")
    assert ev is not None and resolve_identity([ev]).gender is Gender.WOMAN
    assert parse_musicbrainz_gender({"gender": "Attack Helicopter"}, "c", "d") is None
    assert parse_musicbrainz_gender({"name": "x"}, "c", "d") is None


def test_musicbrainz_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        parse_musicbrainz_gender(["x"], "c", "d")


def test_wikidata_p21_extracts_qid() -> None:
    payload = {"claims": {"P21": [{"mainsnak": {"datavalue": {"value": {"id": "Q6581072"}}}}]}}
    ev = parse_wikidata_p21(payload, "wd://1", "2026-05-31")
    assert ev is not None and ev.kind is SourceKind.WIKIDATA_P21
    assert resolve_identity([ev]).gender is Gender.WOMAN


def test_wikidata_p21_missing_or_malformed_returns_none() -> None:
    assert parse_wikidata_p21({"claims": {}}, "c", "d") is None
    assert parse_wikidata_p21({"claims": {"P21": [{}]}}, "c", "d") is None
    assert (
        parse_wikidata_p21(
            {"claims": {"P21": [{"mainsnak": {"datavalue": {"value": {"id": 5}}}}]}}, "c", "d"
        )
        is None
    )


def test_discogs_lineup_extracts_fronts_with_own_identity() -> None:
    payload = {
        "members": [
            {
                "name": "Lead",
                "role": "Lead Vocals",
                "identity_statement": {"value": "woman", "citation": "c"},
            },
            {"name": "Drums", "role": "Drums"},  # not a front → ignored
        ]
    }
    fronts, evidence = parse_discogs_lineup(payload, "dc://1", "2026-05-31")
    assert len(fronts) == 1
    assert fronts[0].identity.gender is Gender.WOMAN
    assert evidence and evidence[0].kind is SourceKind.DISCOGS_LINEUP


def test_discogs_no_fronts_yields_no_composition_evidence() -> None:
    fronts, evidence = parse_discogs_lineup({"members": [{"name": "D", "role": "Drums"}]}, "c", "d")
    assert fronts == [] and evidence == []
