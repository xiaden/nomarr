"""Tests for nomarr.components.ml.calibration.ml_calibration_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.calibration.ml_calibration_comp import (
    apply_minmax_calibration,
    compute_calibration_def_hash,
    compute_global_calibration_hash,
    derive_percentiles_from_sparse_histogram,
    generate_calibration_from_histogram,
    get_default_histogram_spec,
    get_sparse_histogram,
)


@pytest.mark.unit
@pytest.mark.mocked
class TestGetSparseHistogram:
    """Tests for constructor-backed sparse histogram generation."""

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
        mock_db.library.list_tags_by_name.return_value = [
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
        mock_db.library.list_tags_by_name.assert_called_once_with(name="nom:happy_sigmoid_ast20260101", limit=50000)

    def test_returns_empty_when_model_metadata_is_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model.return_value = None

        result = get_sparse_histogram(mock_db, model_id="ml_models/missing", label="happy")

        assert result == []
        mock_db.library.list_all_tag_names.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
class TestApplyMinmaxCalibration:
    """Tests for ``apply_minmax_calibration``."""

    def test_returns_zero_when_score_equals_p5(self) -> None:
        result = apply_minmax_calibration(0.2, {"p5": 0.2, "p95": 0.8})

        assert result == pytest.approx(0.0)

    def test_returns_one_when_score_equals_p95(self) -> None:
        result = apply_minmax_calibration(0.8, {"p5": 0.2, "p95": 0.8})

        assert result == pytest.approx(1.0)

    def test_clamps_to_zero_when_score_below_p5(self) -> None:
        result = apply_minmax_calibration(0.1, {"p5": 0.2, "p95": 0.8})

        assert result == pytest.approx(0.0)

    def test_clamps_to_one_when_score_above_p95(self) -> None:
        result = apply_minmax_calibration(0.9, {"p5": 0.2, "p95": 0.8})

        assert result == pytest.approx(1.0)

    def test_interpolates_score_between_percentiles(self) -> None:
        result = apply_minmax_calibration(0.5, {"p5": 0.2, "p95": 0.8})

        assert result == pytest.approx(0.5)


@pytest.mark.unit
@pytest.mark.mocked
class TestDerivePercentilesFromSparseHistogram:
    """Tests for ``derive_percentiles_from_sparse_histogram``."""

    def test_returns_percentiles_and_counts_for_uniform_distribution(self) -> None:
        sparse_bins = [
            {"min_val": idx * 0.05, "count": 1, "underflow_count": 0, "overflow_count": 0} for idx in range(20)
        ]

        result = derive_percentiles_from_sparse_histogram(
            sparse_bins,
            lo=0.0,
            hi=1.0,
            bin_width=0.05,
            p5_target=0.05,
            p95_target=0.95,
        )

        assert result == {
            "p5": pytest.approx(0.0),
            "p95": pytest.approx(0.9),
            "n": 20,
            "underflow_count": 0,
            "overflow_count": 0,
        }

    def test_passes_through_underflow_and_overflow_counts(self) -> None:
        sparse_bins = [
            {"min_val": 0.2, "count": 3, "underflow_count": 2, "overflow_count": 0},
            {"min_val": 0.7, "count": 2, "underflow_count": 0, "overflow_count": 4},
        ]

        result = derive_percentiles_from_sparse_histogram(sparse_bins)

        assert result["underflow_count"] == 2
        assert result["overflow_count"] == 4
        assert result["n"] == 5
        assert set(result) == {"p5", "p95", "n", "underflow_count", "overflow_count"}

    def test_returns_bounds_and_zero_counts_for_empty_sparse_bins(self) -> None:
        result = derive_percentiles_from_sparse_histogram([], lo=0.1, hi=0.9, bin_width=0.1)

        assert result == {
            "p5": 0.1,
            "p95": 0.9,
            "n": 0,
            "underflow_count": 0,
            "overflow_count": 0,
        }


@pytest.mark.unit
@pytest.mark.mocked
class TestGenerateCalibrationFromHistogram:
    """Tests for ``generate_calibration_from_histogram``."""

    def test_returns_default_payload_when_sparse_histogram_is_empty(self) -> None:
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.ml.calibration.ml_calibration_comp.get_sparse_histogram",
                return_value=[],
            ) as mock_get_sparse_histogram,
            patch(
                "nomarr.components.ml.calibration.ml_calibration_comp.derive_percentiles_from_sparse_histogram"
            ) as mock_derive,
        ):
            result = generate_calibration_from_histogram(
                mock_db,
                model_id="ml_models/model-1",
                head_name="mood_happy",
                label="happy",
                lo=0.1,
                hi=0.9,
                bins=8,
            )

        assert result == {
            "p5": 0.1,
            "p95": 0.9,
            "n": 0,
            "underflow_count": 0,
            "overflow_count": 0,
            "histogram_bins": [],
        }
        mock_get_sparse_histogram.assert_called_once_with(
            mock_db,
            model_id="ml_models/model-1",
            label="happy",
            lo=0.1,
            hi=0.9,
            bins=8,
        )
        mock_derive.assert_not_called()

    def test_returns_percentiles_and_histogram_bins_when_sparse_histogram_exists(self) -> None:
        mock_db = MagicMock()
        sparse_bins = [
            {"min_val": 0.1, "count": 2, "underflow_count": 1, "overflow_count": 0},
            {"min_val": 0.7, "count": 3, "underflow_count": 0, "overflow_count": 4},
        ]

        with (
            patch(
                "nomarr.components.ml.calibration.ml_calibration_comp.get_sparse_histogram",
                return_value=sparse_bins,
            ) as mock_get_sparse_histogram,
            patch(
                "nomarr.components.ml.calibration.ml_calibration_comp.derive_percentiles_from_sparse_histogram",
                return_value={
                    "p5": 0.12,
                    "p95": 0.78,
                    "n": 5,
                    "underflow_count": 1,
                    "overflow_count": 4,
                },
            ) as mock_derive,
        ):
            result = generate_calibration_from_histogram(
                mock_db,
                model_id="ml_models/model-2",
                head_name="mood_happy",
                label="happy",
                lo=0.0,
                hi=1.0,
                bins=10,
            )

        assert result == {
            "p5": 0.12,
            "p95": 0.78,
            "n": 5,
            "underflow_count": 1,
            "overflow_count": 4,
            "histogram_bins": [
                {"val": 0.1, "count": 2},
                {"val": 0.7, "count": 3},
            ],
        }
        mock_get_sparse_histogram.assert_called_once_with(
            mock_db,
            model_id="ml_models/model-2",
            label="happy",
            lo=0.0,
            hi=1.0,
            bins=10,
        )
        mock_derive.assert_called_once_with(
            sparse_bins=sparse_bins,
            lo=0.0,
            hi=1.0,
            bin_width=0.1,
            p5_target=0.05,
            p95_target=0.95,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestComputeCalibrationDefHash:
    """Tests for ``compute_calibration_def_hash``."""

    def test_returns_non_empty_hash(self) -> None:
        result = compute_calibration_def_hash("ml_models/model-1", "mood_happy", "happy")

        assert isinstance(result, str)
        assert result

    def test_returns_same_hash_for_same_inputs(self) -> None:
        result_1 = compute_calibration_def_hash("ml_models/model-1", "mood_happy", "happy")
        result_2 = compute_calibration_def_hash("ml_models/model-1", "mood_happy", "happy")

        assert result_1 == result_2

    def test_returns_different_hash_when_model_id_changes(self) -> None:
        result_1 = compute_calibration_def_hash("ml_models/model-1", "mood_happy", "happy")
        result_2 = compute_calibration_def_hash("ml_models/model-2", "mood_happy", "happy")

        assert result_1 != result_2


@pytest.mark.unit
@pytest.mark.mocked
class TestComputeGlobalCalibrationHash:
    """Tests for ``compute_global_calibration_hash``."""

    def test_returns_non_empty_hash_for_empty_list(self) -> None:
        result = compute_global_calibration_hash([])

        assert isinstance(result, str)
        assert result

    def test_returns_non_empty_hash_for_populated_list(self) -> None:
        result = compute_global_calibration_hash(
            [
                {
                    "_key": "state-1",
                    "calibration_def_hash": "hash-1",
                    "p5": 0.1,
                    "p95": 0.9,
                }
            ]
        )

        assert isinstance(result, str)
        assert result

    def test_returns_same_hash_for_same_logical_list_ordering(self) -> None:
        states = [
            {"_key": "state-b", "calibration_def_hash": "hash-b", "p5": 0.2, "p95": 0.8},
            {"_key": "state-a", "calibration_def_hash": "hash-a", "p5": 0.1, "p95": 0.9},
        ]

        result_1 = compute_global_calibration_hash(states)
        result_2 = compute_global_calibration_hash(list(reversed(states)))

        assert result_1 == result_2


@pytest.mark.unit
@pytest.mark.mocked
class TestGetDefaultHistogramSpec:
    """Tests for ``get_default_histogram_spec``."""

    def test_returns_expected_histogram_fields_and_values(self) -> None:
        result = get_default_histogram_spec("mood_happy")

        assert result == {
            "lo": 0.0,
            "hi": 1.0,
            "bins": 10000,
            "bin_width": pytest.approx(0.0001),
        }
