"""Tests for ``nomarr.components.ml.inference.ml_head_pipeline_comp``."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from nomarr.components.ml.inference.ml_head_pipeline_comp import (
    _build_tag_key,
    run_heads,
    run_single_head,
)
from nomarr.components.ml.onnx.ml_head import ONNXHeadModel
from nomarr.helpers.dto.ml_head_dto import HeadInfo


def _mock_head_model(path: str = "/models/effnet/heads/sigmoid/mood.onnx") -> MagicMock:
    """Build a mock ONNXHeadModel with a meta attribute set up."""
    mock = MagicMock()
    mock._path = path
    return mock


@pytest.mark.unit
class TestBuildTagKey:
    """Tests for _build_tag_key()."""

    def test_returns_first_element_of_build_versioned_tag_key(self) -> None:
        mock_model = _mock_head_model()
        mock_model.meta.build_versioned_tag_key.return_value = ("happy_effnet_mood_happy", "none_0")

        result = _build_tag_key("happy", head_model=mock_model)

        assert result == "happy_effnet_mood_happy"

    def test_calls_build_versioned_tag_key_on_meta(self) -> None:
        mock_model = _mock_head_model()
        mock_model.meta.build_versioned_tag_key.return_value = ("happy_effnet_mood", "none_0")

        _build_tag_key("happy", head_model=mock_model)

        mock_model.meta.build_versioned_tag_key.assert_called_once()

    def test_passes_calib_none_defaults(self) -> None:
        mock_model = _mock_head_model()
        mock_model.meta.build_versioned_tag_key.return_value = ("happy_effnet_mood", "none_0")

        _build_tag_key("happy", head_model=mock_model)

        _, kwargs = mock_model.meta.build_versioned_tag_key.call_args
        assert kwargs.get("calib_method") == "none"
        assert kwargs.get("calib_version") == 0

    def test_normalizes_non_prefix_to_not(self) -> None:
        """normalize_tag_label converts 'non_*' -> 'not_*' before key building."""
        mock_model = _mock_head_model()
        mock_model.meta.build_versioned_tag_key.return_value = ("not_happy_effnet_mood", "none_0")

        _build_tag_key("non_happy", head_model=mock_model)

        positional, _ = mock_model.meta.build_versioned_tag_key.call_args
        assert positional[0] == "not_happy"

    def test_plain_label_passes_through_unchanged(self) -> None:
        mock_model = _mock_head_model()
        mock_model.meta.build_versioned_tag_key.return_value = ("happy_effnet_mood", "none_0")

        _build_tag_key("happy", head_model=mock_model)

        positional, _ = mock_model.meta.build_versioned_tag_key.call_args
        assert positional[0] == "happy"


def _make_sigmoid_head_info() -> HeadInfo:
    """Real HeadInfo for a sigmoid (multilabel) head."""
    return HeadInfo(
        name="mood_happy",
        labels=["happy", "not_happy"],
        backbone="effnet",
        head_type="sigmoid",
        model_stem="mood_happy",
        model_path="/models/effnet/heads/sigmoid/mood_happy.onnx",
        embedding_graph="",
        is_regression_head=False,
    )


def _make_regression_head_info() -> HeadInfo:
    """Real HeadInfo for a regression head."""
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


class _StubSigmoidHeadModel(ONNXHeadModel):
    """Typed test double that returns deterministic sigmoid scores."""

    def _run(self, embeddings: np.ndarray) -> np.ndarray:
        return np.array([[0.9, 0.1]], dtype=np.float32)


class _StubSigmoidMultiSegmentHeadModel(ONNXHeadModel):
    """Typed test double that returns deterministic multilabel segment scores."""

    def _run(self, embeddings: np.ndarray) -> np.ndarray:
        return np.array(
            [
                [0.9, 0.1],
                [0.8, 0.2],
                [0.7, 0.3],
            ],
            dtype=np.float32,
        )


class _StubRegressionMultiSegmentHeadModel(ONNXHeadModel):
    """Typed test double that returns deterministic regression segment scores."""

    def _run(self, embeddings: np.ndarray) -> np.ndarray:
        return np.array(
            [
                [0.65],
                [0.75],
                [0.85],
            ],
            dtype=np.float32,
        )


@pytest.mark.unit
class TestRunSingleHeadWithRealObjects:
    """Tests for run_single_head() using real HeadInfo + ONNXHeadModel (no ONNX session)."""

    def test_success_status_returned(self) -> None:
        hi = _make_sigmoid_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)

        def predict_fn():
            return np.array([[0.9, 0.1]], dtype=np.float32)

        result = run_single_head(model, predict_fn)

        assert result.status == "success"
        assert result.head_name == "mood_happy"

    def test_tag_keys_use_versioned_format(self) -> None:
        hi = _make_sigmoid_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)

        def predict_fn():
            return np.array([[0.9, 0.1]], dtype=np.float32)

        result = run_single_head(model, predict_fn)

        assert result.head_tags is not None
        assert "happy_effnet_mood_happy" in result.head_tags
        assert "not_happy_effnet_mood_happy" in result.head_tags

    def test_head_outputs_created_from_real_head_info(self) -> None:
        hi = _make_sigmoid_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)

        def predict_fn():
            return np.array([[0.9, 0.1]], dtype=np.float32)

        result = run_single_head(model, predict_fn)

        assert result.head_outputs is not None
        assert len(result.head_outputs) > 0
        happy_outputs = [o for o in result.head_outputs if o.label == "happy"]
        assert len(happy_outputs) == 1
        assert happy_outputs[0].head is hi
        assert happy_outputs[0].tier == "high"

    def test_classification_head_captures_raw_output_streams_by_output_index(self) -> None:
        hi = _make_sigmoid_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)

        def predict_fn() -> np.ndarray:
            return np.array(
                [
                    [0.9, 0.1],
                    [0.8, 0.2],
                    [0.7, 0.3],
                ],
                dtype=np.float32,
            )

        result = run_single_head(model, predict_fn)

        assert result.raw_output_streams is not None
        assert [stream.output_index for stream in result.raw_output_streams] == [0, 1]
        assert result.raw_output_streams[0].values == pytest.approx([0.9, 0.8, 0.7])
        assert result.raw_output_streams[1].values == pytest.approx([0.1, 0.2, 0.3])

    def test_regression_head_captures_regression_data(self) -> None:
        hi = _make_regression_head_info()
        model = ONNXHeadModel(
            "/models/effnet/heads/regression/approachability_regression.onnx",
            meta=hi,
        )

        def predict_fn():
            return np.array([[0.65]], dtype=np.float32)

        result = run_single_head(model, predict_fn)

        assert result.status == "success"
        assert result.regression_data is not None
        reg_head_info, raw_values = result.regression_data
        assert reg_head_info is hi
        assert len(raw_values) == 1
        assert abs(raw_values[0] - 0.65) < 1e-5

    def test_regression_head_outputs_is_empty(self) -> None:
        hi = _make_regression_head_info()
        model = ONNXHeadModel(
            "/models/effnet/heads/regression/approachability_regression.onnx",
            meta=hi,
        )

        def predict_fn():
            return np.array([[0.65]], dtype=np.float32)

        result = run_single_head(model, predict_fn)

        assert result.head_outputs == []

    def test_regression_head_captures_single_raw_output_stream(self) -> None:
        hi = _make_regression_head_info()
        model = ONNXHeadModel(
            "/models/effnet/heads/regression/approachability_regression.onnx",
            meta=hi,
        )

        def predict_fn() -> np.ndarray:
            return np.array(
                [
                    [0.65],
                    [0.75],
                    [0.85],
                ],
                dtype=np.float32,
            )

        result = run_single_head(model, predict_fn)

        assert result.raw_output_streams is not None
        assert len(result.raw_output_streams) == 1
        assert result.raw_output_streams[0].output_index == 0
        assert result.raw_output_streams[0].values == pytest.approx([0.65, 0.75, 0.85])

    def test_predict_fn_exception_yields_error_processing(self) -> None:
        hi = _make_sigmoid_head_info()
        model = ONNXHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)

        def failing_predict() -> np.ndarray:
            raise RuntimeError("session not loaded")

        result = run_single_head(model, failing_predict)

        assert result.status == "error_processing"
        assert result.error is not None
        assert "session not loaded" in result.error


@pytest.mark.unit
class TestRunHeads:
    """Tests for run_heads() — dispatches multiple heads in parallel."""

    def test_single_head_succeeds(self) -> None:
        hi = _make_sigmoid_head_info()
        head_model = _StubSigmoidHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)

        tags_accum: dict[str, Any] = {}
        result = run_heads([head_model], np.zeros((1, 64), dtype=np.float32), tags_accum)

        assert result.heads_succeeded == 1
        assert "happy_effnet_mood_happy" in tags_accum

    def test_tags_accumulated_in_passed_dict(self) -> None:
        hi = _make_sigmoid_head_info()
        head_model = _StubSigmoidHeadModel("/models/effnet/heads/sigmoid/mood_happy.onnx", meta=hi)

        tags_accum: dict[str, Any] = {"existing_tag": 1.0}
        run_heads([head_model], np.zeros((1, 64), dtype=np.float32), tags_accum)

        assert "existing_tag" in tags_accum
        assert "happy_effnet_mood_happy" in tags_accum

    def test_run_heads_aggregates_raw_output_streams_by_model_path(self) -> None:
        sigmoid_head_info = _make_sigmoid_head_info()
        regression_head_info = _make_regression_head_info()
        sigmoid_head = _StubSigmoidMultiSegmentHeadModel(sigmoid_head_info.model_path, meta=sigmoid_head_info)
        regression_head = _StubRegressionMultiSegmentHeadModel(
            regression_head_info.model_path,
            meta=regression_head_info,
        )

        tags_accum: dict[str, Any] = {}
        result = run_heads(
            [sigmoid_head, regression_head],
            np.zeros((3, 64), dtype=np.float32),
            tags_accum,
        )

        assert result.heads_succeeded == 2
        assert set(result.raw_output_streams_by_model_path) == {
            sigmoid_head_info.model_path,
            regression_head_info.model_path,
        }
        assert [
            stream.output_index for stream in result.raw_output_streams_by_model_path[sigmoid_head_info.model_path]
        ] == [0, 1]
        assert result.raw_output_streams_by_model_path[sigmoid_head_info.model_path][0].values == pytest.approx(
            [0.9, 0.8, 0.7]
        )
        assert result.raw_output_streams_by_model_path[sigmoid_head_info.model_path][1].values == pytest.approx(
            [0.1, 0.2, 0.3]
        )
        assert [
            stream.output_index for stream in result.raw_output_streams_by_model_path[regression_head_info.model_path]
        ] == [0]
        assert result.raw_output_streams_by_model_path[regression_head_info.model_path][0].values == pytest.approx(
            [0.65, 0.75, 0.85]
        )

    def test_empty_head_list_returns_zero_successes(self) -> None:
        tags_accum: dict[str, Any] = {}
        result = run_heads([], np.zeros((1, 64), dtype=np.float32), tags_accum)

        assert result.heads_succeeded == 0
        assert result.head_results == {}
