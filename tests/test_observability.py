"""Display adapter tests for fairness observability (EXP-01)."""

from __future__ import annotations

import pytest
from recommender.exposure import SEGMENTS, observability_panel
from recommender.hybrid import recommend


def _rankings(profile, catalog, source):
    return {
        lens: recommend(profile, catalog, source, k=len(catalog), lens_strength=lens)
        for lens in (0.0, 0.25, 0.5, 0.75, 1.0)
    }


def test_panel_aligns_rows_and_retention(profile, catalog, source) -> None:
    panel = observability_panel(_rankings(profile, catalog, source), 1.0, k=3)
    assert [row["segment"] for row in panel["exposure_rows"]] == list(SEGMENTS)
    assert panel["retention_row"]["segment"] == "unknown"
    assert all(value == 1.0 for value in panel["retention_row"]["by_lens"].values())


def test_panel_exposure_changes_for_demo(profile, catalog, source) -> None:
    panel = observability_panel(_rankings(profile, catalog, source), 1.0, k=3)
    assert any(row["base_share"] != row["current_share"] for row in panel["exposure_rows"])


def test_panel_rejects_missing_lenses(profile, catalog, source) -> None:
    rankings = _rankings(profile, catalog, source)
    with pytest.raises(ValueError, match="current_lens"):
        observability_panel(rankings, 0.9, k=5)
    with pytest.raises(ValueError, match="base_lens"):
        observability_panel(rankings, 1.0, k=5, base_lens=0.9)
