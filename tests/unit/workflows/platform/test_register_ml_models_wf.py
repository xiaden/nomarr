"""Unit tests for ``register_ml_models_wf``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.workflows.platform.register_ml_models_wf import register_ml_models_workflow


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
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """Known-model reseeding must not overwrite already labeled outputs on restart."""

        onnx_path = tmp_path / "effnet" / "heads" / "sigmoid" / "mood_happy.onnx"
        onnx_path.parent.mkdir(parents=True)
        onnx_path.write_bytes(b"fake")

        db = MagicMock()
        model_id = "ml_models/model-1"
        outputs = [
            {
                "_id": "ml_model_outputs/output-0",
                "output_index": 0,
                "label": "custom-happy",
                "fully_labeled": True,
            },
            {
                "_id": "ml_model_outputs/output-1",
                "output_index": 1,
                "label": None,
                "fully_labeled": False,
            },
        ]

        with (
            patch.dict("sys.modules", {"onnxruntime": _fake_onnxruntime_module(output_count=2)}),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.get_known_outputs",
                return_value=[(0, "happy"), (1, "sad")],
            ),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.upsert_registered_model",
                return_value={"_id": model_id},
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
                    {"_id": "ml_model_outputs/output-0", "label": "custom-happy"},
                    {"_id": "ml_model_outputs/output-1", "label": "sad"},
                ],
            ),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.mark_model_fully_configured",
            ) as mock_mark_configured,
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.mark_model_known",
            ) as mock_mark_known,
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.list_registered_models",
                return_value=[],
            ),
            patch("nomarr.workflows.platform.register_ml_models_wf.prune_registered_model") as mock_prune,
        ):
            register_ml_models_workflow(db, str(tmp_path))

        mock_update_label.assert_called_once_with(
            db,
            output_id="ml_model_outputs/output-1",
            label="sad",
        )
        mock_mark_configured.assert_called_once_with(db, model_id, value=True)
        mock_mark_known.assert_called_once_with(db, model_id, value=True)
        mock_prune.assert_not_called()

    def test_seeds_all_known_outputs_when_model_is_new(
        self,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """New known models should still receive all default labels."""

        onnx_path = tmp_path / "effnet" / "heads" / "sigmoid" / "mood_happy.onnx"
        onnx_path.parent.mkdir(parents=True)
        onnx_path.write_bytes(b"fake")

        db = MagicMock()
        model_id = "ml_models/model-1"
        outputs = [
            {
                "_id": "ml_model_outputs/output-0",
                "output_index": 0,
                "label": None,
                "fully_labeled": False,
            },
            {
                "_id": "ml_model_outputs/output-1",
                "output_index": 1,
                "label": None,
                "fully_labeled": False,
            },
        ]

        with (
            patch.dict("sys.modules", {"onnxruntime": _fake_onnxruntime_module(output_count=2)}),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.get_known_outputs",
                return_value=[(0, "happy"), (1, "sad")],
            ),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.upsert_registered_model",
                return_value={"_id": model_id},
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
                    {"_id": "ml_model_outputs/output-0", "label": "happy"},
                    {"_id": "ml_model_outputs/output-1", "label": "sad"},
                ],
            ),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.mark_model_fully_configured",
            ),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.mark_model_known",
            ),
            patch(
                "nomarr.workflows.platform.register_ml_models_wf.list_registered_models",
                return_value=[],
            ),
            patch("nomarr.workflows.platform.register_ml_models_wf.prune_registered_model"),
        ):
            register_ml_models_workflow(db, str(tmp_path))

        assert mock_update_label.call_args_list == [
            call(db, output_id="ml_model_outputs/output-0", label="happy"),
            call(db, output_id="ml_model_outputs/output-1", label="sad"),
        ]
