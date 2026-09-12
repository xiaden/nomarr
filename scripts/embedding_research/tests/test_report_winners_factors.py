"""Winner/baseline row projection factors."""

from __future__ import annotations

import pandas as pd

from scripts.embedding_research.report._winners import (
    BASELINE_COLUMNS,
    WINNER_COLUMNS,
    baseline_rows,
    winner_rows,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"geometry_id": "g1", "threshold_id": "t-0", "metric": "total_searchable", "value": 1.0},
            {
                "geometry_id": "g1",
                "threshold_id": "observed-baseline:effnet",
                "metric": "baseline_present",
                "value": 1.0,
            },
        ]
    )


def test_winner_and_baseline_projections_have_exact_columns():
    frame = _frame()
    assert list(winner_rows(frame).columns) == [c for c in WINNER_COLUMNS if c in frame.columns]
    assert list(baseline_rows(frame).columns) == [c for c in BASELINE_COLUMNS if c in frame.columns]


def test_empty_inputs_return_empty_frames_with_full_columns():
    assert winner_rows(None).empty
    assert list(winner_rows(None).columns) == WINNER_COLUMNS
    assert baseline_rows(None).empty
    assert list(baseline_rows(None).columns) == BASELINE_COLUMNS
