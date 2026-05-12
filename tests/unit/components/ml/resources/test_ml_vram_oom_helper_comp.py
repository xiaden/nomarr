"""Tests for ``nomarr.components.ml.resources.ml_vram_oom_helper_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.resources.ml_vram_oom_helper_comp import update_model_vram_from_oom


@pytest.mark.unit
def test_update_model_vram_from_existing_meta_value() -> None:
    db = MagicMock()
    db.app.get_meta.return_value = {"value": "1000"}

    result = update_model_vram_from_oom(db, "model.onnx", 800)

    assert result == 1250
    db.app.get_meta.assert_called_once_with("ml_model_vram:model.onnx")
    db.app.upsert_meta.assert_called_once_with("ml_model_vram:model.onnx", {"value": "1250"})


@pytest.mark.unit
def test_update_model_vram_uses_requested_bytes_when_meta_missing() -> None:
    db = MagicMock()
    db.app.get_meta.return_value = None

    result = update_model_vram_from_oom(db, "model.onnx", 800)

    assert result == 1000
    db.app.upsert_meta.assert_called_once_with("ml_model_vram:model.onnx", {"value": "1000"})
