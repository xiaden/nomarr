"""Tests for ``nomarr.components.ml.onnx.ml_discovery_comp`` discovery functions."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.onnx.ml_discovery_comp import (
    discover_head_models,
    discover_head_models_no_db,
)
from nomarr.components.ml.onnx.ml_head import ONNXHeadModel
from nomarr.helpers.dto.ml_head_dto import HeadInfo


def _create_head_onnx(models_dir: str, backbone: str, head_type: str, stem: str) -> str:
    """Create a minimal fake .onnx file at the expected path."""
    head_dir = os.path.join(models_dir, backbone, "heads", head_type)
    os.makedirs(head_dir, exist_ok=True)
    path = os.path.join(head_dir, f"{stem}.onnx")
    with open(path, "wb") as f:
        f.write(b"fake")
    return path


@pytest.mark.unit
class TestDiscoverHeadModelsNoDB:
    """Tests for discover_head_models_no_db()."""

    def test_empty_models_dir_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = discover_head_models_no_db(tmpdir)
        assert result == []

    def test_synthesizes_head_info_with_correct_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_head_onnx(tmpdir, "effnet", "sigmoid", "mood_happy")
            result = discover_head_models_no_db(tmpdir)

        assert len(result) == 1
        model = result[0]
        assert isinstance(model, ONNXHeadModel)
        assert isinstance(model.meta, HeadInfo)
        assert model.meta.backbone == "effnet"
        assert model.meta.head_type == "sigmoid"
        assert model.meta.model_stem == "mood_happy"
        assert model.meta.labels == []

    def test_synthesized_model_path_matches_onnx_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            expected_path = _create_head_onnx(tmpdir, "effnet", "sigmoid", "mood_happy")
            result = discover_head_models_no_db(tmpdir)

        assert result[0].meta.model_path == expected_path
        assert result[0]._path == expected_path

    def test_regression_head_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_head_onnx(tmpdir, "effnet", "regression", "approachability_regression")
            result = discover_head_models_no_db(tmpdir)

        assert len(result) == 1
        assert result[0].meta.is_regression_head is True

    def test_non_regression_head_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_head_onnx(tmpdir, "effnet", "sigmoid", "mood_happy")
            result = discover_head_models_no_db(tmpdir)

        assert result[0].meta.is_regression_head is False

    def test_multiple_heads_are_sorted_by_backbone(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_head_onnx(tmpdir, "yamnet", "sigmoid", "genre_rock")
            _create_head_onnx(tmpdir, "effnet", "sigmoid", "mood_happy")
            result = discover_head_models_no_db(tmpdir)

        assert len(result) == 2
        backbones = [m.meta.backbone for m in result]
        assert backbones == sorted(backbones)

    def test_labels_are_empty_for_all_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_head_onnx(tmpdir, "effnet", "sigmoid", "mood_happy")
            _create_head_onnx(tmpdir, "effnet", "sigmoid", "genre_rock")
            result = discover_head_models_no_db(tmpdir)

        for model in result:
            assert model.meta.labels == []


@pytest.mark.unit
class TestDiscoverHeadModels:
    """Tests for discover_head_models()."""

    def test_passes_head_info_from_db_to_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            onnx_path = _create_head_onnx(tmpdir, "effnet", "sigmoid", "mood_happy")
            hi = HeadInfo(
                name="mood_happy",
                labels=["happy", "not_happy"],
                backbone="effnet",
                head_type="sigmoid",
                model_stem="mood_happy",
                model_path=onnx_path,
                embedding_graph="",
            )
            mock_db = MagicMock()
            with patch(
                "nomarr.components.ml.onnx.ml_discovery_comp.discover_heads",
                return_value=[hi],
            ):
                result = discover_head_models(tmpdir, mock_db)

        assert len(result) == 1
        assert result[0].meta is hi

    def test_head_info_labels_are_present_on_model_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            onnx_path = _create_head_onnx(tmpdir, "effnet", "sigmoid", "mood_happy")
            mock_db = MagicMock()
            hi = HeadInfo(
                name="mood_happy",
                labels=["happy", "not_happy"],
                backbone="effnet",
                head_type="sigmoid",
                model_stem="mood_happy",
                model_path=onnx_path,
                embedding_graph="",
            )
            with patch(
                "nomarr.components.ml.onnx.ml_discovery_comp.discover_heads",
                return_value=[hi],
            ):
                result = discover_head_models(tmpdir, mock_db)

        assert result[0].meta.labels == ["happy", "not_happy"]

    def test_db_exception_synthesizes_fallback_meta(self) -> None:
        """When discover_heads raises, models get synthesized HeadInfo with empty labels."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_head_onnx(tmpdir, "effnet", "sigmoid", "mood_happy")
            mock_db = MagicMock()
            with patch(
                "nomarr.components.ml.onnx.ml_discovery_comp.discover_heads",
                side_effect=RuntimeError("DB unavailable"),
            ):
                result = discover_head_models(tmpdir, mock_db)

        assert len(result) == 1
        assert result[0].meta.labels == []
        assert result[0].meta.backbone == "effnet"
        assert result[0].meta.head_type == "sigmoid"
        assert result[0].meta.model_stem == "mood_happy"
        assert result[0].meta.model_path == os.path.join(tmpdir, "effnet", "heads", "sigmoid", "mood_happy.onnx")
