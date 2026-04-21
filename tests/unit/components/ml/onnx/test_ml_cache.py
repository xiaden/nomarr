import tempfile
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.onnx.ml_cache import ONNXModelCache
from nomarr.components.ml.onnx.ml_head import ONNXHeadModel
from nomarr.helpers.dto.ml_head_dto import HeadInfo


@dataclass
class _FakeBackbone:
    backbone_name: str


def _make_head(
    backbone: str,
    head_type: str = "sigmoid",
    model_stem: str = "mood_happy",
) -> ONNXHeadModel:
    hi = HeadInfo(
        name=model_stem,
        labels=["happy", "not_happy"],
        backbone=backbone,
        head_type=head_type,
        model_stem=model_stem,
        model_path=f"/models/{backbone}/heads/{head_type}/{model_stem}.onnx",
        embedding_graph="",
    )
    return ONNXHeadModel(hi.model_path, meta=hi)


@pytest.mark.unit
class TestONNXModelCacheInit:
    def test_no_models_dir_produces_empty_cache(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_backbone_models",
                return_value=[],
            ),
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_head_models_no_db",
                return_value=[],
            ),
        ):
            cache = ONNXModelCache(tmpdir, device="cpu")

        assert cache.backbones == {}
        assert cache.heads == {}

    def test_heads_grouped_by_meta_backbone(self) -> None:
        heads = [
            _make_head(backbone="effnet", model_stem="mood_happy"),
            _make_head(backbone="yamnet", model_stem="genre_rock"),
        ]

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_backbone_models",
                return_value=[],
            ),
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_head_models_no_db",
                return_value=heads,
            ),
        ):
            cache = ONNXModelCache(tmpdir, device="cpu")

        assert set(cache.heads) == {"effnet", "yamnet"}

    def test_heads_from_same_backbone_grouped_together(self) -> None:
        heads = [
            _make_head(backbone="effnet", model_stem="mood_happy"),
            _make_head(backbone="effnet", model_stem="genre_rock"),
        ]

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_backbone_models",
                return_value=[],
            ),
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_head_models_no_db",
                return_value=heads,
            ),
        ):
            cache = ONNXModelCache(tmpdir, device="cpu")

        assert len(cache.heads["effnet"]) == 2

    def test_with_db_calls_discover_head_models_not_no_db(self) -> None:
        db = MagicMock()

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_backbone_models",
                return_value=[],
            ),
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_head_models",
                return_value=[],
            ) as mock_discover_with_db,
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_head_models_no_db",
                return_value=[],
            ) as mock_discover_no_db,
        ):
            ONNXModelCache(tmpdir, device="cpu", db=db)

        mock_discover_with_db.assert_called_once_with(tmpdir, db)
        mock_discover_no_db.assert_not_called()

    def test_without_db_calls_discover_head_models_no_db(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_backbone_models",
                return_value=[],
            ),
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_head_models",
                return_value=[],
            ) as mock_discover_with_db,
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_head_models_no_db",
                return_value=[],
            ) as mock_discover_no_db,
        ):
            ONNXModelCache(tmpdir, device="cpu", db=None)

        mock_discover_with_db.assert_not_called()
        mock_discover_no_db.assert_called_once_with(tmpdir)


@pytest.mark.unit
class TestONNXModelCacheModelCount:
    def test_model_count_is_zero_for_empty_cache(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_backbone_models",
                return_value=[],
            ),
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_head_models_no_db",
                return_value=[],
            ),
        ):
            cache = ONNXModelCache(tmpdir, device="cpu")

        assert cache.model_count == 0

    def test_model_count_sums_backbones_and_heads(self) -> None:
        backbones = [_FakeBackbone("effnet"), _FakeBackbone("yamnet")]
        heads = [
            _make_head(backbone="effnet", model_stem="mood_happy"),
            _make_head(backbone="effnet", model_stem="genre_rock"),
            _make_head(backbone="yamnet", model_stem="instrumental"),
        ]

        with (
            tempfile.TemporaryDirectory() as tmpdir,
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_backbone_models",
                return_value=backbones,
            ),
            patch(
                "nomarr.components.ml.onnx.ml_cache.discover_head_models_no_db",
                return_value=heads,
            ),
        ):
            cache = ONNXModelCache(tmpdir, device="cpu")

        assert cache.model_count == 5
