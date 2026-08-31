"""Tests for the calibration export bundle workflow.

Pins the attribute-based export contract (P3-S2): the workflow reads
``CalibrationState`` domain attributes (``state.head_name``/``p5``/``p95``) and
writes ``method="histogram"`` — it must not index into a storage-row dict.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.calibration_state_dataclass import CalibrationState
from nomarr.workflows.calibration.export_calibration_bundle_wf import export_calibration_bundle_wf

if TYPE_CHECKING:
    from pathlib import Path


def _state(**overrides: object) -> CalibrationState:
    base: dict[str, object] = {
        "model_id": "model-1",
        "head_name": "mood_happy",
        "label": "happy",
        "calibration_def_hash": "hash-1",
        "histogram_bins": [{"val": 0.1, "count": 2}],
        "p5": 0.1,
        "p95": 0.9,
        "sample_count": 12,
        "histogram": {"lo": 0.0, "hi": 1.0, "bins": 10, "bin_width": 0.1},
    }
    base.update(overrides)
    return CalibrationState(**base)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.mocked
class TestExportCalibrationBundle:
    def test_exports_using_calibration_state_attributes(self, tmp_path: Path) -> None:
        state = _state()
        out = tmp_path / "calibration.json"

        with (
            patch(
                "nomarr.workflows.calibration.export_calibration_bundle_wf.load_all_calibration_states",
                return_value=[state],
            ) as mock_load,
            patch(
                "nomarr.workflows.calibration.export_calibration_bundle_wf.get_calibration_version",
                return_value="gv-1",
            ),
            patch(
                "nomarr.workflows.calibration.export_calibration_bundle_wf.now_ms",
                return_value=MagicMock(value=1_700_000_000_000),
            ),
            patch(
                "nomarr.workflows.calibration.export_calibration_bundle_wf.format_wall_timestamp",
                return_value="2026-01-01T00:00:00Z",
            ),
        ):
            result = export_calibration_bundle_wf(MagicMock(), str(out))

        mock_load.assert_called_once()
        assert result == {
            "exported_count": 1,
            "output_path": str(out),
            "global_version": "gv-1",
        }

        bundle = json.loads(out.read_text())
        assert bundle["labels"] == {"happy": {"p5": 0.1, "p95": 0.9, "method": "histogram"}}
        assert bundle["metadata"]["global_version"] == "gv-1"
        assert bundle["metadata"]["calibration_count"] == 1

    def test_exports_skips_state_without_p5_or_p95(self, tmp_path: Path) -> None:
        state = _state(p5=None, p95=None)
        out = tmp_path / "calibration.json"

        with (
            patch(
                "nomarr.workflows.calibration.export_calibration_bundle_wf.load_all_calibration_states",
                return_value=[state],
            ),
            patch(
                "nomarr.workflows.calibration.export_calibration_bundle_wf.get_calibration_version",
                return_value="gv-1",
            ),
            patch(
                "nomarr.workflows.calibration.export_calibration_bundle_wf.now_ms",
                return_value=MagicMock(value=1_700_000_000_000),
            ),
            patch(
                "nomarr.workflows.calibration.export_calibration_bundle_wf.format_wall_timestamp",
                return_value="2026-01-01T00:00:00Z",
            ),
        ):
            result = export_calibration_bundle_wf(MagicMock(), str(out))

        assert result["exported_count"] == 0
        bundle = json.loads(out.read_text())
        assert bundle["labels"] == {}

    def test_raises_when_no_calibrations(self, tmp_path: Path) -> None:
        with (
            patch(
                "nomarr.workflows.calibration.export_calibration_bundle_wf.load_all_calibration_states",
                return_value=[],
            ),
            pytest.raises(ValueError, match="No calibrations in database to export"),
        ):
            export_calibration_bundle_wf(MagicMock(), str(tmp_path / "calibration.json"))
