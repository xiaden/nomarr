"""Unit tests for ``register_ml_models_wf``."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.helpers.dataclasses.ml_model_dataclass import RegisteredModel
from nomarr.helpers.dataclasses.ml_model_output_dataclass import ModelOutput
from nomarr.workflows.platform.register_ml_models_wf import register_ml_models_workflow

if TYPE_CHECKING:
    from pathlib import Path


def _fake_onnxruntime_module(output_count: int) -> SimpleNamespace:
    """Return a fake ``onnxruntime`` module with a configurable output shape."""

    class _FakeSession:
        def __init__(self, _path: str, providers: list[str]) -> None:
            self.providers = providers

        def get_outputs(self) -> list[SimpleNamespace]:
            return [SimpleNamespace(shape=[1, output_count])]

    return SimpleNamespace(InferenceSession=_FakeSession)


@pytest.mark.unit
@pytest.mark.mocked
class TestRegisterMlModelsWorkflow:
    """Tests for ``register_ml_models_workflow``."""

    def test_preserves_existing_known_labels_and_only_seeds_missing_outputs(
        self,
        tmp_path: Path,
    ) -> None:
        """Known-model reseeding must not overwrite already labeled outputs on restart."""
        onnx_path = tmp_path / "effnet" / "heads" / "sigmoid" / "mood_happy.onnx"
        onnx_path.parent.mkdir(parents=True)
        onnx_path.write_bytes(b"fake")

        db = MagicMock()
        model_id = "model-1"
        outputs = [
            ModelOutput(
                output_id="ml_model_outputs/output-0",
                output_index=0,
                label="custom-happy",
                fully_labeled=True,
            ),
            ModelOutput(
                output_id="ml_model_outputs/output-1",
                output_index=1,
                label=None,
                fully_labeled=False,
            ),
        ]

        with (
            patch.dict("sys.modules", {"onnxruntime": _fake_onnxruntime_module(output_count=2)}),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.get_known_outputs",
                return_value=[(0, "happy"), (1, "sad")],
            ),
            patch.object(
                db.ml,
                "register_model",
                return_value=RegisteredModel(
                    id=model_id,
                    path=str(onnx_path),
                    model_type="sigmoid",
                    backbone_id="effnet",
                    backbone="effnet",
                    head_type="sigmoid",
                    model_stem="mood_happy",
                    output_count=2,
                    fully_configured=False,
                    is_known=False,
                    source="known",
                    head_release_date="",
                    embedder_release_date="",
                ),
            ),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.ensure_model_outputs",
                return_value=outputs,
            ),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.update_model_output_label",
            ) as mock_update_label,
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.list_fully_labeled_model_outputs",
                return_value=[
                    ModelOutput(output_id="ml_model_outputs/output-0", label="custom-happy"),
                    ModelOutput(output_id="ml_model_outputs/output-1", label="sad"),
                ],
            ),
        ):
            register_ml_models_workflow(db, str(tmp_path))

        mock_update_label.assert_called_once_with(
            db,
            model_id=model_id,
            output_id="ml_model_outputs/output-1",
            label="sad",
        )
        db.ml.mark_model_fully_configured.assert_called_once_with(model_id, value=True)
        db.ml.mark_model_known.assert_called_once_with(model_id, value=True)
        db.ml.remove_model.assert_not_called()

    def test_seeds_all_known_outputs_when_model_is_new(
        self,
        tmp_path: Path,
    ) -> None:
        """New known models should still receive all default labels."""
        onnx_path = tmp_path / "effnet" / "heads" / "sigmoid" / "mood_happy.onnx"
        onnx_path.parent.mkdir(parents=True)
        onnx_path.write_bytes(b"fake")

        db = MagicMock()
        model_id = "model-1"
        outputs = [
            ModelOutput(
                output_id="ml_model_outputs/output-0",
                output_index=0,
                label=None,
                fully_labeled=False,
            ),
            ModelOutput(
                output_id="ml_model_outputs/output-1",
                output_index=1,
                label=None,
                fully_labeled=False,
            ),
        ]

        with (
            patch.dict("sys.modules", {"onnxruntime": _fake_onnxruntime_module(output_count=2)}),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.get_known_outputs",
                return_value=[(0, "happy"), (1, "sad")],
            ),
            patch.object(
                db.ml,
                "register_model",
                return_value=RegisteredModel(
                    id=model_id,
                    path=str(onnx_path),
                    model_type="sigmoid",
                    backbone_id="effnet",
                    backbone="effnet",
                    head_type="sigmoid",
                    model_stem="mood_happy",
                    output_count=2,
                    fully_configured=False,
                    is_known=False,
                    source="known",
                    head_release_date="",
                    embedder_release_date="",
                ),
            ),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.ensure_model_outputs",
                return_value=outputs,
            ),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.update_model_output_label",
            ) as mock_update_label,
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.list_fully_labeled_model_outputs",
                return_value=[
                    ModelOutput(output_id="ml_model_outputs/output-0", label="happy"),
                    ModelOutput(output_id="ml_model_outputs/output-1", label="sad"),
                ],
            ),
        ):
            register_ml_models_workflow(db, str(tmp_path))

        assert mock_update_label.call_args_list == [
            call(db, model_id=model_id, output_id="ml_model_outputs/output-0", label="happy"),
            call(db, model_id=model_id, output_id="ml_model_outputs/output-1", label="sad"),
        ]
