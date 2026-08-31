"""Tests for the histogram calibration generation workflow.

Pins the attribute-based generation contract (P3-S1/S2): the workflow loads the
``CalibrationState`` list via ``load_all_calibration_states`` and passes it
directly to ``compute_global_calibration_hash`` (list[CalibrationState]), and
calls ``save_calibration_state`` with the model_id keyword.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.workflows.calibration.generate_calibration_wf import generate_histogram_calibration_wf

_WF = "nomarr.workflows.calibration.generate_calibration_wf"


def _head(name: str = "mood", labels: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=name, labels=labels or ["happy"], model_path="/models/m.onnx")


@pytest.mark.unit
@pytest.mark.mocked
class TestGenerateHistogramCalibration:
    def test_computes_global_hash_from_calibration_state_list(self) -> None:
        db = MagicMock()
        model_doc = MagicMock()
        model_doc.id = "model-1"
        db.ml.get_model_by_path.return_value = model_doc
        calib_states = [MagicMock()]

        with (
            patch(f"{_WF}.discover_heads", return_value=[_head()]),
            patch(f"{_WF}.normalize_tag_label", side_effect=lambda label: label),
            patch(
                f"{_WF}.generate_calibration_from_histogram",
                return_value={"p5": 0.1, "p95": 0.9, "n": 12, "underflow_count": 1, "overflow_count": 2},
            ),
            patch(f"{_WF}.compute_calibration_def_hash", return_value="hash-1"),
            patch(f"{_WF}.save_calibration_state"),
            patch(f"{_WF}.load_all_calibration_states", return_value=calib_states) as mock_load,
            patch(f"{_WF}.compute_global_calibration_hash", return_value="gv-1") as mock_hash,
            patch(f"{_WF}.set_calibration_version"),
            patch(f"{_WF}.set_calibration_last_run"),
        ):
            result = generate_histogram_calibration_wf(db, "/models")

        # The global hash is computed over the CalibrationState list, not dict rows.
        mock_load.assert_called_once_with(db)
        mock_hash.assert_called_once_with(calib_states)
        assert result["global_version"] == "gv-1"
        assert result["heads_success"] == 1

    def test_saves_state_with_model_id_keyword(self) -> None:
        db = MagicMock()
        model_doc = MagicMock()
        model_doc.id = "model-1"
        db.ml.get_model_by_path.return_value = model_doc

        with (
            patch(f"{_WF}.discover_heads", return_value=[_head(name="mood", labels=["happy", "sad"])]),
            patch(f"{_WF}.normalize_tag_label", side_effect=lambda label: label),
            patch(
                f"{_WF}.generate_calibration_from_histogram",
                return_value={"p5": 0.1, "p95": 0.9, "n": 12, "underflow_count": 1, "overflow_count": 2},
            ),
            patch(f"{_WF}.compute_calibration_def_hash", return_value="hash-1"),
            patch(f"{_WF}.save_calibration_state") as mock_save,
            patch(f"{_WF}.load_all_calibration_states", return_value=[]),
            patch(f"{_WF}.compute_global_calibration_hash", return_value="gv-1"),
            patch(f"{_WF}.set_calibration_version"),
            patch(f"{_WF}.set_calibration_last_run"),
        ):
            result = generate_histogram_calibration_wf(db, "/models")

        assert result["heads_success"] == 2
        mock_save.assert_any_call(
            db,
            model_id="model-1",
            head_name="mood",
            label="happy",
            calibration_def_hash="hash-1",
            histogram_spec={"lo": 0.0, "hi": 1.0, "bins": 10000, "bin_width": 0.0001},
            p5=0.1,
            p95=0.9,
            sample_count=12,
            underflow_count=1,
            overflow_count=2,
            histogram_bins=None,
        )

    def test_returns_zero_when_no_heads(self) -> None:
        db = MagicMock()

        with patch(f"{_WF}.discover_heads", return_value=[]):
            result = generate_histogram_calibration_wf(db, "/models")

        assert result["version"] == 0
        assert result["heads_processed"] == 0
