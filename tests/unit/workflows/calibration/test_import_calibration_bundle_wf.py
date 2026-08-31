"""Tests for the calibration import bundle workflow.

Pins the v2-JSON boundary contract (P4-S6 / P3-S2): the workflow parses
``n``/``underflow_count``/``overflow_count`` from the bundle and calls
``save_calibration_state`` with the model_id resolved by
``(backbone, embedder_release_date)`` lookup, then recomputes the global
version from the loaded ``CalibrationState`` list.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from nomarr.workflows.calibration.import_calibration_bundle_wf import import_calibration_bundle_wf

if TYPE_CHECKING:
    from pathlib import Path


def _write_bundle(path: Path, labels: dict, metadata: dict | None = None) -> None:
    bundle = {"labels": labels}
    if metadata is not None:
        bundle["metadata"] = metadata
    path.write_text(json.dumps(bundle))


def _model(backbone: str = "ast", embedder_release_date: str = "2026-01-01", model_id: str = "model-1") -> MagicMock:
    model = MagicMock()
    model.id = model_id
    model.backbone = backbone
    model.embedder_release_date = embedder_release_date
    return model


@pytest.mark.unit
@pytest.mark.mocked
class TestImportCalibrationBundle:
    def test_imports_parsing_n_and_model_key_at_boundary(self, tmp_path: Path) -> None:
        path = tmp_path / "calibration.json"
        _write_bundle(
            path,
            {
                "happy": {
                    "p5": 0.1,
                    "p95": 0.9,
                    "model_key": "ast-20260101",
                    "n": 12,
                    "underflow_count": 1,
                    "overflow_count": 2,
                }
            },
        )
        db = MagicMock()
        db.ml.list_models.return_value = [_model()]

        with (
            patch(
                "nomarr.workflows.calibration.import_calibration_bundle_wf.compute_calibration_def_hash",
                return_value="hash-1",
            ),
            patch(
                "nomarr.workflows.calibration.import_calibration_bundle_wf.load_all_calibration_states",
                return_value=[MagicMock()],
            ),
            patch(
                "nomarr.workflows.calibration.import_calibration_bundle_wf.compute_global_calibration_hash",
                return_value="gv-1",
            ),
            patch(
                "nomarr.workflows.calibration.import_calibration_bundle_wf.save_calibration_state",
            ) as mock_save,
            patch(
                "nomarr.workflows.calibration.import_calibration_bundle_wf.set_calibration_version",
            ) as mock_set_version,
        ):
            result = import_calibration_bundle_wf(db, str(path))

        assert result["imported_count"] == 1
        assert result["no_model_count"] == 0
        assert result["global_version"] == "gv-1"
        mock_save.assert_called_once_with(
            db,
            model_id="model-1",
            head_name="mood_happy",
            label="happy",
            calibration_def_hash="hash-1",
            histogram_spec={"lo": 0.0, "hi": 1.0, "bins": 10000, "bin_width": 0.0001},
            p5=0.1,
            p95=0.9,
            sample_count=12,
            underflow_count=1,
            overflow_count=2,
        )
        mock_set_version.assert_called_once_with(db, "gv-1")

    def test_skips_when_no_matching_model(self, tmp_path: Path) -> None:
        path = tmp_path / "calibration.json"
        _write_bundle(path, {"happy": {"p5": 0.1, "p95": 0.9, "model_key": "unknown-20260101"}})
        db = MagicMock()
        db.ml.list_models.return_value = [_model()]

        with (
            patch(
                "nomarr.workflows.calibration.import_calibration_bundle_wf.compute_calibration_def_hash",
            ),
            patch(
                "nomarr.workflows.calibration.import_calibration_bundle_wf.load_all_calibration_states",
                return_value=[],
            ),
            patch(
                "nomarr.workflows.calibration.import_calibration_bundle_wf.compute_global_calibration_hash",
                return_value="gv-empty",
            ),
            patch(
                "nomarr.workflows.calibration.import_calibration_bundle_wf.save_calibration_state",
            ) as mock_save,
            patch(
                "nomarr.workflows.calibration.import_calibration_bundle_wf.set_calibration_version",
            ),
        ):
            result = import_calibration_bundle_wf(db, str(path))

        assert result["imported_count"] == 0
        assert result["no_model_count"] == 1
        mock_save.assert_not_called()

    def test_raises_when_labels_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "calibration.json"
        path.write_text(json.dumps({}))

        with pytest.raises(ValueError, match="Bundle contains no calibrations"):
            import_calibration_bundle_wf(MagicMock(), str(path))
