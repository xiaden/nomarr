"""Tests for nomarr.components.ml.calibration.ml_calibration_comp module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.calibration.ml_calibration_comp import (
    apply_minmax_calibration,
    compute_calibration_def_hash,
    compute_global_calibration_hash,
    derive_percentiles_from_sparse_histogram,
    export_calibration_state_to_json,
    generate_calibration_from_histogram,
    get_default_histogram_spec,
    get_sparse_histogram,
    import_calibration_state_from_json,
)
from nomarr.helpers.dataclasses.calibration_state_dataclass import CalibrationState
from nomarr.helpers.dataclasses.ml_model_dataclass import RegisteredModel
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef


@pytest.mark.unit
@pytest.mark.mocked
class TestGetSparseHistogram:
    """Tests for constructor-backed sparse histogram generation."""

    def test_aggregates_matching_numeric_values_into_sorted_sparse_bins(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model = MagicMock(
            return_value=RegisteredModel(
                id="model-1",
                path="/m.onnx",
                model_type="cls",
                backbone_id="b-ast",
                backbone="ast",
                head_type="mood",
                model_stem="m",
                output_count=2,
                fully_configured=True,
                is_known=True,
                source="local",
                head_release_date="2026-01-01",
                embedder_release_date="2026-01-01",
            )
        )
        mock_db.library.list_all_tag_names = MagicMock(
            return_value=[
                "nom:sigmoid_happy_ast_20260101",
                "nom:sigmoid_sad_ast_20260101",
                "genre",
            ]
        )
        tag_name = "nom:sigmoid_happy_ast_20260101"
        mock_db.library.list_tags = MagicMock(
            return_value=(
                TagRef(name=tag_name, value=-0.2, namespace="nom"),
                TagRef(name=tag_name, value=0.1, namespace="nom"),
                TagRef(name=tag_name, value=0.11, namespace="nom"),
                TagRef(name=tag_name, value=1.2, namespace="nom"),
                TagRef(name=tag_name, value="0.3", namespace="nom"),
                TagRef(name=tag_name, value=True, namespace="nom"),
            )
        )

        result = get_sparse_histogram(
            mock_db,
            model_id="ml_models/model-1",
            label="happy",
            lo=0.0,
            hi=1.0,
            bins=10,
        )

        assert result == [
            {"min_val": 0.1, "count": 2, "underflow_count": 0, "overflow_count": 2},
            {"min_val": 0.2, "count": 1, "underflow_count": 2, "overflow_count": 1},
            {"min_val": 0.9, "count": 1, "underflow_count": 3, "overflow_count": 0},
        ]
        mock_db.library.list_all_tag_names.assert_called_once_with(limit=10000)
        mock_db.library.list_tags.assert_called_once_with(name=tag_name, limit=50000)

    def test_returns_empty_when_model_metadata_is_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model = MagicMock(return_value=None)

        result = get_sparse_histogram(mock_db, model_id="ml_models/missing", label="happy")

        assert result == []
        mock_db.library.list_all_tag_names.assert_not_called()

    def test_non_numeric_tag_values_are_skipped_without_raising(self) -> None:
        """Narrowing TagRef.value: numeric strings are accepted; values that are
        not int/float/str (e.g. None) are skipped rather than raising."""
        mock_db = MagicMock()
        mock_db.ml.get_model = MagicMock(
            return_value=RegisteredModel(
                id="model-1",
                path="/m.onnx",
                model_type="cls",
                backbone_id="b-ast",
                backbone="ast",
                head_type="mood",
                model_stem="m",
                output_count=2,
                fully_configured=True,
                is_known=True,
                source="local",
                head_release_date="2026-01-01",
                embedder_release_date="2026-01-01",
            )
        )
        tag_name = "nom:sigmoid_happy_ast_20260101"
        mock_db.library.list_all_tag_names = MagicMock(return_value=[tag_name])
        mock_db.library.list_tags = MagicMock(
            return_value=(
                TagRef(name=tag_name, value="0.1", namespace="nom"),
                TagRef(name=tag_name, value=None, namespace="nom"),
                TagRef(name=tag_name, value=0.11, namespace="nom"),
            )
        )

        result = get_sparse_histogram(
            mock_db,
            model_id="ml_models/model-1",
            label="happy",
            lo=0.0,
            hi=1.0,
            bins=10,
        )

        # None is skipped; "0.1" (string) and 0.11 (int/float) are both accepted
        # into the same sparse bin. No exception is raised for the non-numeric
        # value.
        assert result == [{"min_val": 0.1, "count": 2, "underflow_count": 0, "overflow_count": 0}]

    def test_empty_list_hashes_deterministically(self) -> None:
        assert compute_global_calibration_hash([]) == compute_global_calibration_hash([])
        assert isinstance(compute_global_calibration_hash([]), str)


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
        result = derive_percentiles_from_sparse_histogram([], lo=0.1, hi=0.9)

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
                new_callable=MagicMock,
                return_value=[],
            ),
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
                new_callable=MagicMock,
                return_value=sparse_bins,
            ),
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
        mock_derive.assert_called_once_with(
            sparse_bins=sparse_bins,
            lo=0.0,
            hi=1.0,
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
                CalibrationState(
                    model_id="model-1",
                    head_name="mood_happy",
                    label="happy",
                    calibration_def_hash="hash-1",
                    p5=0.1,
                    p95=0.9,
                )
            ]
        )

        assert isinstance(result, str)
        assert result

    def test_returns_same_hash_for_same_logical_list_ordering(self) -> None:
        states = [
            CalibrationState(
                model_id="model-2",
                head_name="mood_happy",
                label="happy",
                calibration_def_hash="hash-b",
                p5=0.2,
                p95=0.8,
            ),
            CalibrationState(
                model_id="model-1",
                head_name="mood_happy",
                label="happy",
                calibration_def_hash="hash-a",
                p5=0.1,
                p95=0.9,
            ),
        ]

        result_1 = compute_global_calibration_hash(states)
        result_2 = compute_global_calibration_hash(list(reversed(states)))

        assert result_1 == result_2

    def test_ordering_invariance_by_semantic_identity(self) -> None:
        states = [
            CalibrationState(
                model_id="model-1", head_name="mood_happy", label="happy", calibration_def_hash="h1", p5=0.1, p95=0.9
            ),
            CalibrationState(
                model_id="model-1", head_name="mood_happy", label="sad", calibration_def_hash="h2", p5=0.2, p95=0.8
            ),
        ]

        assert compute_global_calibration_hash(states) == compute_global_calibration_hash(list(reversed(states)))

    def test_storage_row_id_change_does_not_affect_hash(self) -> None:
        base = CalibrationState(
            model_id="model-1", head_name="mood_happy", label="happy", calibration_def_hash="h1", p5=0.1, p95=0.9
        )
        # CalibrationState has no storage row id; a hypothetical storage id can
        # only be expressed as semantic fields. A change to those fields must
        # change the hash, proving no opaque storage id is hashed.
        changed = CalibrationState(
            model_id="model-1", head_name="mood_happy", label="happy", calibration_def_hash="h1", p5=0.11, p95=0.9
        )
        assert compute_global_calibration_hash([base]) != compute_global_calibration_hash([changed])

    def test_returns_deterministic_value_for_fixed_state_set(self) -> None:
        states = [
            CalibrationState(
                model_id="model-1", head_name="mood_happy", label="happy", calibration_def_hash="h1", p5=0.1, p95=0.9
            ),
            CalibrationState(
                model_id="model-1", head_name="mood_happy", label="sad", calibration_def_hash="h2", p5=0.2, p95=0.8
            ),
        ]

        expected = compute_global_calibration_hash(states)
        assert compute_global_calibration_hash(states) == expected


@pytest.mark.unit
@pytest.mark.mocked
class TestGetDefaultHistogramSpec:
    """Tests for ``get_default_histogram_spec``."""

    def test_returns_expected_histogram_fields_and_values(self) -> None:
        result = get_default_histogram_spec()

        assert result == {
            "lo": 0.0,
            "hi": 1.0,
            "bins": 10000,
        }


def _registered_model(
    *,
    model_id: str = "model-1",
    backbone: str = "ast",
    embedder_release_date: str = "2026-01-01",
) -> RegisteredModel:
    """Build a minimal domain model for import/export model resolution."""
    return RegisteredModel(
        id=model_id,
        path=f"/models/{model_id}.onnx",
        model_type="cls",
        backbone_id="b-ast",
        backbone=backbone,
        head_type="mood",
        model_stem=model_id,
        output_count=2,
        fully_configured=True,
        is_known=True,
        source="local",
        head_release_date="2026-01-01",
        embedder_release_date=embedder_release_date,
    )


@pytest.mark.unit
@pytest.mark.mocked
class TestExportCalibrationStateToJson:
    """Tests for ``export_calibration_state_to_json`` v2 wire shape.

    The export is an adapter-boundary projection: the JSON file uses backbone +
    ``embedder_release_date`` (not ``model_id``) for model resolution, the wire
    field ``n`` carries ``sample_count``, and the ``version: 2`` envelope is
    preserved. No storage row id / ``state_data`` envelope is ever written.
    """

    def test_exports_v2_envelope_with_n_equals_sample_count(self, tmp_path) -> None:
        mock_db = MagicMock()
        state = CalibrationState(
            model_id="model-1",
            head_name="mood_happy",
            label="happy",
            calibration_def_hash="hash-1",
            histogram={"lo": 0.0, "hi": 1.0, "bins": 10},
            histogram_bins=[{"val": 0.1, "count": 2}],
            p5=0.1,
            p95=0.9,
            sample_count=12,
            underflow_count=1,
            overflow_count=2,
        )
        mock_db.ml.list_calibration_states.return_value = [state]
        mock_db.ml.list_models.return_value = [_registered_model()]
        out = tmp_path / "calibration.json"

        result = export_calibration_state_to_json(mock_db, str(out))

        assert result == {"calibrations_exported": 1, "path": str(out)}
        payload = json.loads(out.read_text())
        assert payload["version"] == 2
        assert payload["format"] == "nomarr_calibration_state"
        assert len(payload["calibrations"]) == 1
        entry = payload["calibrations"][0]
        # Model resolved via backbone + embedder_release_date, not model_id.
        assert entry["backbone"] == "ast"
        assert entry["embedder_release_date"] == "2026-01-01"
        assert entry["head_name"] == "mood_happy"
        assert entry["label"] == "happy"
        assert entry["p5"] == 0.1
        assert entry["p95"] == 0.9
        assert entry["n"] == 12  # wire field n = sample_count
        assert entry["underflow_count"] == 1
        assert entry["overflow_count"] == 2
        assert entry["histogram_bins"] == [{"val": 0.1, "count": 2}]
        # No persistence identity or storage envelope leaks into the wire file.
        assert "model_id" not in entry
        assert "state_data" not in entry
        assert "id" not in entry
        assert "_key" not in entry

    def test_exports_blank_model_fields_when_lookup_missing(self, tmp_path) -> None:
        mock_db = MagicMock()
        state = CalibrationState(model_id="model-ghost", head_name="h", label="x", p5=0.1, p95=0.9, sample_count=3)
        mock_db.ml.list_calibration_states.return_value = [state]
        mock_db.ml.list_models.return_value = []
        out = tmp_path / "calibration.json"

        export_calibration_state_to_json(mock_db, str(out))

        entry = json.loads(out.read_text())["calibrations"][0]
        assert entry["backbone"] == ""
        assert entry["embedder_release_date"] == ""


@pytest.mark.unit
@pytest.mark.mocked
class TestImportCalibrationStateFromJson:
    """Tests for ``import_calibration_state_from_json`` model-scoped import.

    The importer resolves ``model_id`` via ``(backbone, embedder_release_date)``,
    checks existence via the canonical 3-arg ``get_calibration_state_view`` and
    converts the wire field ``n`` back to ``sample_count`` at the boundary.
    """

    def _write_v2(self, path, calibrations: list[dict]) -> None:
        path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "format": "nomarr_calibration_state",
                    "calibrations": calibrations,
                }
            )
        )

    @staticmethod
    def _v2_entry() -> dict:
        return {
            "backbone": "ast",
            "embedder_release_date": "2026-01-01",
            "head_name": "mood_happy",
            "label": "happy",
            "calibration_def_hash": "hash-1",
            "histogram": {"lo": 0.0, "hi": 1.0, "bins": 10},
            "p5": 0.1,
            "p95": 0.9,
            "n": 12,
            "underflow_count": 1,
            "overflow_count": 2,
            "histogram_bins": [{"val": 0.1, "count": 2}],
        }

    def test_imports_using_3arg_lookup_and_n_to_sample_count(self, tmp_path) -> None:
        path = tmp_path / "calibration.json"
        self._write_v2(path, [self._v2_entry()])
        mock_db = MagicMock()
        mock_db.ml.list_models.return_value = [_registered_model()]
        mock_db.ml.get_calibration_state_view.return_value = None

        result = import_calibration_state_from_json(mock_db, str(path))

        assert result == {"calibrations_imported": 1, "skipped": 0, "no_model": 0}
        # Canonical 3-arg model-scoped lookup.
        mock_db.ml.get_calibration_state_view.assert_called_once_with("model-1", "mood_happy", "happy")
        mock_db.ml.replace_calibration_state.assert_called_once_with(
            CalibrationState(
                model_id="model-1",
                head_name="mood_happy",
                label="happy",
                calibration_def_hash="hash-1",
                histogram={"lo": 0.0, "hi": 1.0, "bins": 10},
                histogram_bins=[{"val": 0.1, "count": 2}],
                p5=0.1,
                p95=0.9,
                sample_count=12,
                underflow_count=1,
                overflow_count=2,
            )
        )

    def test_skips_when_existing_def_hash_matches_without_overwrite(self, tmp_path) -> None:
        path = tmp_path / "calibration.json"
        self._write_v2(path, [self._v2_entry()])
        mock_db = MagicMock()
        mock_db.ml.list_models.return_value = [_registered_model()]
        existing = CalibrationState(
            model_id="model-1", head_name="mood_happy", label="happy", calibration_def_hash="hash-1"
        )
        mock_db.ml.get_calibration_state_view.return_value = existing

        result = import_calibration_state_from_json(mock_db, str(path))

        assert result == {"calibrations_imported": 0, "skipped": 1, "no_model": 0}
        mock_db.ml.replace_calibration_state.assert_not_called()

    def test_overwrite_when_existing_def_hash_matches(self, tmp_path) -> None:
        path = tmp_path / "calibration.json"
        self._write_v2(path, [self._v2_entry()])
        mock_db = MagicMock()
        mock_db.ml.list_models.return_value = [_registered_model()]
        existing = CalibrationState(
            model_id="model-1", head_name="mood_happy", label="happy", calibration_def_hash="hash-1"
        )
        mock_db.ml.get_calibration_state_view.return_value = existing

        result = import_calibration_state_from_json(mock_db, str(path), overwrite=True)

        assert result == {"calibrations_imported": 1, "skipped": 0, "no_model": 0}
        mock_db.ml.replace_calibration_state.assert_called_once()

    def test_skips_when_no_matching_model(self, tmp_path) -> None:
        path = tmp_path / "calibration.json"
        self._write_v2(path, [self._v2_entry()])
        mock_db = MagicMock()
        mock_db.ml.list_models.return_value = []

        result = import_calibration_state_from_json(mock_db, str(path))

        assert result == {"calibrations_imported": 0, "skipped": 0, "no_model": 1}
        mock_db.ml.get_calibration_state_view.assert_not_called()
        mock_db.ml.replace_calibration_state.assert_not_called()

    def test_raises_on_unknown_format(self, tmp_path) -> None:
        path = tmp_path / "calibration.json"
        path.write_text(json.dumps({"version": 1, "format": "other", "calibrations": []}))

        with pytest.raises(ValueError, match="Invalid calibration export format"):
            import_calibration_state_from_json(MagicMock(), str(path))
