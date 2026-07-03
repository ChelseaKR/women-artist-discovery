"""Thumbs feedback math + the artist-scoped, bounded contract, on hand-built artists."""

from __future__ import annotations

import pytest
from pipeline.models import Gender
from recommender.feedback import MAX_FEEDBACK, Feedback, feedback_adjustment

from .conftest import make_artist


def _vote(artist_id: str, vote: int, ts: int = 100, username: str = "chelsea") -> Feedback:
    return Feedback(username=username, artist_id=artist_id, vote=vote, ts=ts)


def test_no_feedback_is_identity() -> None:
    artist = make_artist("a")
    assert feedback_adjustment(artist, [], strength=1.0) == 0.0


def test_feedback_for_a_different_artist_does_not_apply() -> None:
    artist = make_artist("a")
    other_votes = [_vote("b", 1), _vote("b", -1), _vote("c", 1)]
    assert feedback_adjustment(artist, other_votes, strength=1.0) == 0.0


def test_thumbs_up_moves_an_artist_up() -> None:
    artist = make_artist("a")
    delta = feedback_adjustment(artist, [_vote("a", 1)], strength=1.0)
    assert delta > 0.0


def test_thumbs_down_moves_an_artist_down() -> None:
    artist = make_artist("a")
    delta = feedback_adjustment(artist, [_vote("a", -1)], strength=1.0)
    assert delta < 0.0


def test_up_and_down_votes_are_symmetric() -> None:
    artist = make_artist("a")
    up = feedback_adjustment(artist, [_vote("a", 1)], strength=1.0)
    down = feedback_adjustment(artist, [_vote("a", -1)], strength=1.0)
    assert up == pytest.approx(-down)


def test_votes_net_out() -> None:
    artist = make_artist("a")
    votes = [_vote("a", 1), _vote("a", -1)]
    assert feedback_adjustment(artist, votes, strength=1.0) == 0.0


def test_zero_strength_disables_feedback() -> None:
    artist = make_artist("a")
    votes = [_vote("a", 1), _vote("a", 1), _vote("a", 1)]
    assert feedback_adjustment(artist, votes, strength=0.0) == 0.0


def test_boundedness_even_with_many_votes() -> None:
    artist = make_artist("a")
    # tanh saturates to (numerically) exactly 1.0 well before 1000 votes, so the
    # bound must be a non-strict <=; the strict-inequality case (still room to
    # grow) is covered separately below with a smaller vote count.
    lots_of_up = [_vote("a", 1, ts=i) for i in range(1000)]
    lots_of_down = [_vote("a", -1, ts=i) for i in range(1000)]
    assert 0.0 < feedback_adjustment(artist, lots_of_up, strength=1.0) <= MAX_FEEDBACK
    assert -MAX_FEEDBACK <= feedback_adjustment(artist, lots_of_down, strength=1.0) < 0.0


def test_boundedness_has_headroom_for_a_single_vote() -> None:
    artist = make_artist("a")
    assert 0.0 < feedback_adjustment(artist, [_vote("a", 1)], strength=1.0) < MAX_FEEDBACK


def test_out_of_range_strength_is_clamped_not_amplified() -> None:
    artist = make_artist("a")
    votes = [_vote("a", 1)]
    normal = feedback_adjustment(artist, votes, strength=1.0)
    over = feedback_adjustment(artist, votes, strength=5.0)
    assert over == normal


def test_determinism() -> None:
    artist = make_artist("a")
    votes = [_vote("a", 1), _vote("a", -1), _vote("a", 1)]
    first = feedback_adjustment(artist, votes, strength=0.7)
    second = feedback_adjustment(artist, list(reversed(votes)), strength=0.7)
    assert first == second == feedback_adjustment(artist, votes, strength=0.7)


def test_vote_must_be_plus_or_minus_one() -> None:
    with pytest.raises(ValueError, match="vote must be"):
        Feedback(username="u", artist_id="a", vote=2, ts=1)
    with pytest.raises(ValueError, match="vote must be"):
        Feedback(username="u", artist_id="a", vote=0, ts=1)


def test_feedback_is_artist_scoped_not_identity_scoped() -> None:
    """Thumbs-down on one woman artist must not touch another woman artist.

    This is the fairness guarantee this module must not re-break: adjustments
    are keyed to ``artist_id``, never to a shared identity label.
    """
    woman_a = make_artist("woman-a", gender=Gender.WOMAN)
    woman_b = make_artist("woman-b", gender=Gender.WOMAN)
    votes = [_vote("woman-a", -1), _vote("woman-a", -1), _vote("woman-a", -1)]

    assert feedback_adjustment(woman_a, votes, strength=1.0) < 0.0
    assert feedback_adjustment(woman_b, votes, strength=1.0) == 0.0
