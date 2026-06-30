"""M3 acceptance: the hybrid beats a popularity baseline on held-out scrobbles."""

from __future__ import annotations

import pytest
from recommender.eval import (
    average_precision_at_k,
    evaluate,
    ground_truth,
    precision_recall_at_k,
    temporal_split,
    to_report,
)


def test_hybrid_beats_popularity_baseline(demo_user, scrobbles, catalog, source) -> None:
    report = to_report(evaluate(demo_user, scrobbles, catalog, source, k=5))
    assert report["hybrid_beats_popularity"] is True
    assert report["models"]["hybrid"]["map_at_k"] > report["models"]["popularity"]["map_at_k"]
    assert (
        report["models"]["hybrid"]["recall_at_k"] >= report["models"]["popularity"]["recall_at_k"]
    )


def test_temporal_split_is_chronological(scrobbles) -> None:
    train, test = temporal_split(scrobbles, 0.7)
    assert train and test
    assert max(s.ts for s in train) <= min(s.ts for s in test)


def test_ground_truth_is_test_only_discoveries(scrobbles) -> None:
    train, test = temporal_split(scrobbles, 0.7)
    gt = ground_truth(train, test)
    train_ids = {s.artist_id for s in train}
    assert gt
    assert not (gt & train_ids)


def test_precision_recall_math() -> None:
    ranked = ["a", "b", "c", "d"]
    positives = {"a", "c", "z"}
    p, r = precision_recall_at_k(ranked, positives, k=4)
    assert p == 0.5  # 2 of 4
    assert r == pytest.approx(2 / 3)


def test_average_precision_math() -> None:
    ranked = ["a", "x", "b"]
    positives = {"a", "b"}
    # hits at ranks 1 and 3 → (1/1 + 2/3) / 2
    assert average_precision_at_k(ranked, positives, k=3) == pytest.approx((1 + 2 / 3) / 2)


def test_empty_positives_score_zero() -> None:
    assert average_precision_at_k(["a"], set(), k=1) == 0.0
    assert precision_recall_at_k([], {"a"}, k=5) == (0.0, 0.0)


def test_split_rejects_bad_fraction(scrobbles) -> None:
    with pytest.raises(ValueError):
        temporal_split(scrobbles, 1.0)
