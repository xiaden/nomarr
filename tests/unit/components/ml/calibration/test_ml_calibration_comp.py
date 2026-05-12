"""Tests for nomarr.components.ml.calibration.ml_calibration_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.calibration.ml_calibration_comp import get_sparse_histogram


class TestGetSparseHistogram:
    """Tests for constructor-backed sparse histogram generation."""

    @pytest.mark.unit
    def test_aggregates_matching_numeric_values_into_sorted_sparse_bins(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model.return_value = {
            "_id": "ml_models/model-1",
            "backbone": "ast",
            "embedder_release_date": "2026-01-01",
        }
        mock_db.library.list_all_tag_names.return_value = [
            "nom:happy_sigmoid_ast20260101",
            "nom:sad_sigmoid_ast20260101",
            "genre",
        ]
        mock_db.library.get_tags_by_name.return_value = [
            {"value": -0.2},
            {"value": 0.1},
            {"value": 0.11},
            {"value": 1.2},
            {"value": "0.3"},
            {"value": True},
        ]

        result = get_sparse_histogram(
            mock_db,
            model_id="ml_models/model-1",
            label="happy",
            lo=0.0,
            hi=1.0,
            bins=10,
        )

        assert result == [
            {"min_val": 0.0, "count": 1, "underflow_count": 1, "overflow_count": 0},
            {"min_val": 0.1, "count": 2, "underflow_count": 0, "overflow_count": 0},
            {"min_val": 0.9, "count": 1, "underflow_count": 0, "overflow_count": 1},
        ]
        mock_db.library.list_all_tag_names.assert_called_once_with(limit=10000)
        mock_db.library.get_tags_by_name.assert_called_once_with(name="nom:happy_sigmoid_ast20260101", limit=50000)

    @pytest.mark.unit
    def test_returns_empty_when_model_metadata_is_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model.return_value = None

        result = get_sparse_histogram(mock_db, model_id="ml_models/missing", label="happy")

        assert result == []
        mock_db.library.list_all_tag_names.assert_not_called()
