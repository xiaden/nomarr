"""Geometry winner and observed-baseline report rows, kept strictly separate.

Winner rows are the exact threshold representation evidence; observed-baseline rows are
the mandatory global-medoid baseline evidence.  They share the same complete identity
axes but are never merged, and no strategy key is decoded here.
"""

from __future__ import annotations

import pandas as pd

from ._retrieval import IDENTITY_COLUMNS

WINNER_COLUMNS = [*IDENTITY_COLUMNS, "metric", "value"]
BASELINE_COLUMNS = [*IDENTITY_COLUMNS, "metric", "value"]


def _project(frame: pd.DataFrame | None, columns: list[str]) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=columns)
    return frame[[column for column in columns if column in frame.columns]].reset_index(drop=True)


def winner_rows(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Exact winner representation rows (never observed-baseline rows)."""
    return _project(frame, WINNER_COLUMNS)


def baseline_rows(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Exact observed global-medoid baseline rows (never winner rows)."""
    return _project(frame, BASELINE_COLUMNS)


__all__ = ["BASELINE_COLUMNS", "WINNER_COLUMNS", "baseline_rows", "winner_rows"]
