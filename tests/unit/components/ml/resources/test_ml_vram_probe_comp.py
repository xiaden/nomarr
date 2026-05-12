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
    def test_persists_measurements_via_app_meta(self) -> None:
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

        assert db.app.upsert_meta.call_args_list == [
            call("ml_model_vram:backbone.onnx", {"value": "110"}),
            call("ml_model_vram:head.onnx", {"value": str(sys.maxsize)}),
        ]


@pytest.mark.unit
class TestHasModelVramMeasurements:
    def test_returns_true_when_matching_keys_exist(self) -> None:
        db = MagicMock()
        db.app.list_meta_keys_by_prefix.return_value = ["ml_model_vram:model.onnx"]

        assert has_model_vram_measurements(db) is True
        db.app.list_meta_keys_by_prefix.assert_called_once_with("ml_model_vram:")

    def test_returns_false_when_no_matching_keys_exist(self) -> None:
        db = MagicMock()
        db.app.list_meta_keys_by_prefix.return_value = []

        assert has_model_vram_measurements(db) is False


@pytest.mark.unit
class TestClearModelVramMeasurements:
    def test_deletes_each_matching_meta_key(self) -> None:
        db = MagicMock()
        db.app.list_meta_keys_by_prefix.return_value = [
            "ml_model_vram:first.onnx",
            "ml_model_vram:second.onnx",
        ]

        clear_model_vram_measurements(db)

        db.app.list_meta_keys_by_prefix.assert_called_once_with("ml_model_vram:")
        assert db.app.delete_meta.call_args_list == [
            call("ml_model_vram:first.onnx"),
            call("ml_model_vram:second.onnx"),
        ]
