"""M3 acceptance: the hybrid beats a popularity baseline on held-out scrobbles."""

from __future__ import annotations

import pytest
from recommender.eval import (
    EvalResult,
    average_precision_at_k,
    check_regression,
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


def _result(**overrides: float) -> EvalResult:
    base = {
        "model": "hybrid",
        "k": 5,
        "precision_at_k": 0.6,
        "recall_at_k": 0.75,
        "map_at_k": 0.6875,
        "n_positives": 4,
    }
    base.update(overrides)
    return EvalResult(**base)  # type: ignore[arg-type]


def test_check_regression_passes_at_baseline() -> None:
    baseline = {"precision_at_k": 0.6, "recall_at_k": 0.75, "map_at_k": 0.6875}
    result = check_regression(_result(), baseline)
    assert result["regressed"] is False


def test_check_regression_flags_a_real_drop() -> None:
    baseline = {"precision_at_k": 0.6, "recall_at_k": 0.75, "map_at_k": 0.6875}
    # map_at_k drops well past the default 10% tolerance floor (0.6188).
    result = check_regression(_result(map_at_k=0.4), baseline)
    assert result["regressed"] is True
    assert result["metrics"]["map_at_k"]["regressed"] is True
    assert result["metrics"]["precision_at_k"]["regressed"] is False


def test_check_regression_tolerates_small_drops() -> None:
    baseline = {"map_at_k": 0.6875}
    # a 5% drop is within the default 10% tolerance.
    result = check_regression(_result(map_at_k=0.6875 * 0.95), baseline)
    assert result["regressed"] is False


def test_check_regression_skips_metrics_absent_from_baseline() -> None:
    result = check_regression(_result(precision_at_k=0.0), {"map_at_k": 0.6875})
    assert result["regressed"] is False
    assert "precision_at_k" not in result["metrics"]
