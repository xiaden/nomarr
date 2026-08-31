"""Tests for ``nomarr.components.ml.resources.ml_vram_probe_comp``."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.ml.resources.ml_vram_probe_comp import (
    clear_model_vram_measurements,
    has_model_vram_measurements,
    probe_all_models,
)


@pytest.mark.unit
class TestProbeAllModels:
    def test_persists_measurements_via_set_model_vram_limit(self) -> None:
        db = MagicMock()
        backbone = MagicMock()
        backbone._path = "backbone.onnx"
        head = MagicMock()
        head._path = "head.onnx"

        with (
            patch(
                "nomarr.components.ml.resources.ml_vram_probe_comp.discover_backbone_models",
                return_value=[backbone],
            ),
            patch(
                "nomarr.components.ml.resources.ml_vram_probe_comp.discover_head_models_no_db",
                return_value=[head],
            ),
            patch(
                "nomarr.components.ml.resources.ml_vram_probe_comp.get_vram_usage_mb",
                return_value={"used_mb": 100, "total_mb": 1000},
            ),
            patch("nomarr.components.ml.resources.ml_vram_probe_comp._init_cuda_context"),
            patch(
                "nomarr.components.ml.resources.ml_vram_probe_comp._make_probe_waveform",
                return_value="waveform",
            ),
            patch(
                "nomarr.components.ml.resources.ml_vram_probe_comp._probe_single_model",
                side_effect=[100, None],
            ),
        ):
            probe_all_models(db, "models")

        assert db.app.set_model_vram_limit.call_args_list == [
            call("backbone.onnx", 110),
            call("head.onnx", sys.maxsize),
        ]


@pytest.mark.unit
class TestHasModelVramMeasurements:
    def test_returns_true_when_matching_docs_exist(self) -> None:
        db = MagicMock()
        db.app.list_model_vram_limits.return_value = [MagicMock()]

        assert has_model_vram_measurements(db) is True
        db.app.list_model_vram_limits.assert_called_once_with()

    def test_returns_false_when_no_matching_docs_exist(self) -> None:
        db = MagicMock()
        db.app.list_model_vram_limits.return_value = []

        assert has_model_vram_measurements(db) is False


@pytest.mark.unit
class TestClearModelVramMeasurements:
    def test_deletes_via_atomic_clear(self) -> None:
        db = MagicMock()
        db.app.clear_model_vram_limits.return_value = 2

        clear_model_vram_measurements(db)

        db.app.clear_model_vram_limits.assert_called_once_with()
