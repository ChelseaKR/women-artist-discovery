"""EXP-06 — Temporal taste profiles: era windows + recency decay on build_profile."""

from __future__ import annotations

import pytest
from pipeline.ingest import build_profile
from pipeline.models import Scrobble
from recommender.eval import evaluate, to_report

DAY = 86400

_FIXED_SCROBBLES = [
    Scrobble("mitski", "Mitski", "Track A", 1_700_000_000),
    Scrobble("mitski", "Mitski", "Track B", 1_700_003_600),
    Scrobble("mitski", "Mitski", "Track C", 1_700_007_200),
    Scrobble("big-thief", "Big Thief", "Track D", 1_700_010_800),
    Scrobble("big-thief", "Big Thief", "Track E", 1_700_014_400),
    Scrobble("shamir", "Shamir", "Track F", 1_700_018_000),
]


def test_default_build_profile_matches_old_integer_counts() -> None:
    """(a) With era/half-life both None, weights equal the old flat play counts."""
    profile = build_profile("demo", _FIXED_SCROBBLES)
    assert profile.play_counts == {"mitski": 3.0, "big-thief": 2.0, "shamir": 1.0}
    assert profile.top_artists(1) == ["mitski"]


def test_era_window_excludes_plays_outside_range() -> None:
    """(b) Only scrobbles within the inclusive [era_start, era_end] window count."""
    profile = build_profile(
        "demo",
        _FIXED_SCROBBLES,
        era_start=1_700_007_200,  # Track C onward
        era_end=1_700_014_400,  # through Track E
    )
    # mitski: only Track C survives; big-thief: both Track D and E survive;
    # shamir's only play (Track F) is after the window and is excluded entirely.
    assert profile.play_counts == {"mitski": 1.0, "big-thief": 2.0}
    assert "shamir" not in profile.play_counts


def test_era_window_boundaries_are_inclusive() -> None:
    ts = _FIXED_SCROBBLES[0].ts
    profile = build_profile("demo", _FIXED_SCROBBLES, era_start=ts, era_end=ts)
    assert profile.play_counts == {"mitski": 1.0}


@pytest.mark.parametrize("half_life", [0.0, -1.0])
def test_half_life_must_be_positive(half_life: float) -> None:
    with pytest.raises(ValueError, match="half_life_days must be positive"):
        build_profile("demo", _FIXED_SCROBBLES, half_life_days=half_life)


def test_era_window_rejects_reversed_bounds() -> None:
    with pytest.raises(ValueError, match="era_start"):
        build_profile("demo", _FIXED_SCROBBLES, era_start=20, era_end=10)


def test_half_life_weights_a_play_now_about_2x_a_play_one_half_life_ago() -> None:
    """(c) A play at now_ts should weigh ~2x an otherwise-identical play one
    half-life earlier — same artist, so we isolate the ratio via two solo artists.
    """
    half_life_days = 30.0
    now_ts = 1_700_000_000
    one_half_life_ago = now_ts - int(half_life_days * DAY)
    scrobbles = [
        Scrobble("recent-artist", "Recent Artist", "t", now_ts),
        Scrobble("older-artist", "Older Artist", "t", one_half_life_ago),
    ]
    profile = build_profile("demo", scrobbles, now_ts=now_ts, half_life_days=half_life_days)
    recent_weight = profile.play_counts["recent-artist"]
    older_weight = profile.play_counts["older-artist"]
    assert recent_weight == pytest.approx(1.0)
    assert older_weight == pytest.approx(0.5, abs=1e-9)
    assert recent_weight / older_weight == pytest.approx(2.0, rel=1e-6)


def test_recent_heavy_artist_outranks_older_heavy_artist_at_equal_raw_counts() -> None:
    """(c) Two artists with identical raw play counts; decay should favor the
    one whose plays are more recent."""
    half_life_days = 14.0
    now_ts = 1_700_000_000
    old_ts = now_ts - int(60 * DAY)  # ~4.3 half-lives back: heavily decayed
    scrobbles = []
    for i in range(5):
        scrobbles.append(Scrobble("recent-heavy", "Recent Heavy", f"t{i}", now_ts - i * 3600))
    for i in range(5):
        scrobbles.append(Scrobble("older-heavy", "Older Heavy", f"t{i}", old_ts - i * 3600))

    flat = build_profile("demo", scrobbles)
    assert flat.play_counts["recent-heavy"] == flat.play_counts["older-heavy"] == 5.0

    decayed = build_profile("demo", scrobbles, now_ts=now_ts, half_life_days=half_life_days)
    assert decayed.play_counts["recent-heavy"] > decayed.play_counts["older-heavy"]
    assert decayed.top_artists(1) == ["recent-heavy"]


def test_half_life_defaults_now_ts_to_max_scrobble_ts_for_reproducibility() -> None:
    """now_ts defaults to max(ts) in the (era-filtered) scrobbles, not the wall clock."""
    max_ts = max(s.ts for s in _FIXED_SCROBBLES)
    explicit = build_profile("demo", _FIXED_SCROBBLES, now_ts=max_ts, half_life_days=10.0)
    defaulted = build_profile("demo", _FIXED_SCROBBLES, half_life_days=10.0)
    assert explicit.play_counts == defaulted.play_counts
    # The most recent play (max ts) should carry the undecayed weight of 1.0.
    most_recent_artist = max(_FIXED_SCROBBLES, key=lambda s: s.ts).artist_id
    assert defaulted.play_counts[most_recent_artist] == pytest.approx(1.0)


def test_half_life_weighting_is_deterministic() -> None:
    """(d) Same inputs -> identical float weights, run to run."""
    a = build_profile("demo", _FIXED_SCROBBLES, half_life_days=45.0)
    b = build_profile("demo", _FIXED_SCROBBLES, half_life_days=45.0)
    assert a.play_counts == b.play_counts


def test_era_and_half_life_can_combine() -> None:
    """Era filtering happens before decay weighting; both can be given together."""
    profile = build_profile(
        "demo",
        _FIXED_SCROBBLES,
        era_start=1_700_000_000,
        era_end=1_700_010_800,
        half_life_days=30.0,
    )
    assert set(profile.play_counts) == {"mitski", "big-thief"}
    # The window's own latest play (Track D, era_end) is undecayed: weight 1.0.
    assert profile.play_counts["big-thief"] == pytest.approx(1.0)


def test_decay_variant_present_in_evaluate_output(demo_user, scrobbles, catalog, source) -> None:
    """The eval harness exposes a decay-on comparison alongside decay-off hybrid."""
    results = evaluate(demo_user, scrobbles, catalog, source, k=5)
    assert "hybrid_decay" in results
    assert results["hybrid_decay"].k == 5

    report = to_report(results)
    assert "hybrid_decay" in report["models"]
    assert "decay_map_at_k_delta" in report
    assert "decay_improves_map_at_k" in report


def test_decay_variant_is_deterministic(demo_user, scrobbles, catalog, source) -> None:
    a = to_report(evaluate(demo_user, scrobbles, catalog, source, k=5))
    b = to_report(evaluate(demo_user, scrobbles, catalog, source, k=5))
    assert a["models"]["hybrid_decay"] == b["models"]["hybrid_decay"]
