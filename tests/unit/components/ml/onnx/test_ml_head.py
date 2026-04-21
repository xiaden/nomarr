"""Tests for ``nomarr.components.ml.onnx.ml_head``."""

from __future__ import annotations

import pytest

from nomarr.components.ml.onnx.ml_head import ONNXHeadModel, head_parts_from_path
from nomarr.helpers.dto.ml_head_dto import HeadInfo


def _make_head_info() -> HeadInfo:
    return HeadInfo(
        name="mood_happy",
        labels=["happy", "not_happy"],
        backbone="effnet",
        head_type="sigmoid",
        model_stem="mood_happy",
        model_path="/models/effnet/heads/sigmoid/mood_happy.onnx",
        embedding_graph="",
    )


@pytest.mark.unit
class TestONNXHeadModelInit:
    """Tests for ONNXHeadModel.__init__ composition (meta: HeadInfo)."""

    def test_init_with_meta_sets_meta_attribute(self) -> None:
        hi = _make_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)
        assert model.meta is hi

    def test_init_resets_node_attrs_to_none(self) -> None:
        hi = _make_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)
        assert model.input_node is None
        assert model.output_node is None
        assert model.input_dim is None
        assert model.num_classes is None

    def test_init_node_attrs_none_even_with_meta(self) -> None:
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=_make_head_info())
        assert model.input_node is None
        assert model.output_node is None
        assert model.input_dim is None
        assert model.num_classes is None

    def test_init_stores_path_on_base(self) -> None:
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=_make_head_info())
        assert model._path == "/models/effnet/heads/sigmoid/mood_happy.onnx"


@pytest.mark.unit
class TestHeadPartsFromPath:
    """Tests for head_parts_from_path()."""

    def test_parses_standard_structure(self) -> None:
        path = "/models/effnet/heads/sigmoid/mood_happy.onnx"
        backbone, head_type, model_name = head_parts_from_path(path)
        assert backbone == "effnet"
        assert head_type == "sigmoid"
        assert model_name == "mood_happy"

    def test_parses_regression_head(self) -> None:
        path = "/models/yamnet/heads/regression/approachability_regression.onnx"
        backbone, head_type, model_name = head_parts_from_path(path)
        assert backbone == "yamnet"
        assert head_type == "regression"
        assert model_name == "approachability_regression"

    def test_parses_musicnn_backbone(self) -> None:
        path = "/models/musicnn/heads/sigmoid/genre_rock.onnx"
        backbone, head_type, model_name = head_parts_from_path(path)
        assert backbone == "musicnn"
        assert head_type == "sigmoid"
        assert model_name == "genre_rock"

    def test_raises_on_missing_heads_segment(self) -> None:
        path = "/models/effnet/embeddings/model.onnx"
        with pytest.raises(ValueError, match="Cannot derive head info"):
            head_parts_from_path(path)

    def test_raises_on_root_only_path(self) -> None:
        path = "/mood_happy.onnx"
        with pytest.raises(ValueError):
            head_parts_from_path(path)


def _make_regression_head_info() -> HeadInfo:
    return HeadInfo(
        name="approachability_regression",
        labels=["approachability"],
        backbone="effnet",
        head_type="regression",
        model_stem="approachability_regression",
        model_path="/models/effnet/heads/regression/approachability_regression.onnx",
        embedding_graph="",
        is_regression_head=True,
    )


@pytest.mark.unit
class TestONNXHeadModelWithRealMeta:
    """Tests that ONNXHeadModel composition with real HeadInfo works correctly."""

    def test_meta_attributes_accessible_via_model(self) -> None:
        hi = _make_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)
        assert model.meta.name == "mood_happy"
        assert model.meta.backbone == "effnet"
        assert model.meta.head_type == "sigmoid"

    def test_meta_labels_preserved(self) -> None:
        hi = _make_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)
        assert model.meta.labels == ["happy", "not_happy"]

    def test_build_versioned_tag_key_through_meta(self) -> None:
        hi = _make_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)
        key, cal_id = model.meta.build_versioned_tag_key("happy")
        assert key == "happy_effnet_mood_happy"
        assert cal_id == "none_0"

    def test_sigmoid_head_is_not_regression(self) -> None:
        hi = _make_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)
        assert model.meta.is_regression_head is False

    def test_regression_head_info_has_is_regression_head_true(self) -> None:
        hi = _make_regression_head_info()
        model = ONNXHeadModel(
            "/models/effnet/heads/regression/approachability_regression.onnx",
            meta=hi,
        )
        assert model.meta.is_regression_head is True

    def test_versioned_tag_key_uses_calib_none_by_default(self) -> None:
        hi = _make_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)
        _, cal_id = model.meta.build_versioned_tag_key("happy")
        assert cal_id == "none_0"
