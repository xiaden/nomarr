"""Tests for ``nomarr.components.ml.onnx.ml_model_registry_comp``."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.onnx.ml_model_registry_comp import (
    ensure_model_outputs,
    list_fully_labeled_model_outputs,
    list_model_outputs_for_model,
    update_model_output_label,
)
from nomarr.helpers.dataclasses.ml_model_output_dataclass import ModelOutput


@pytest.mark.unit
class TestListModelOutputsForModel:
    """Tests for ``list_model_outputs_for_model``."""

    def test_delegates_to_facade(self) -> None:
        mock_db = MagicMock()
        expected = [ModelOutput(output_id="output-1", output_index=0)]
        mock_db.ml.list_model_outputs.return_value = expected

        result = list_model_outputs_for_model(mock_db, "model-1")

        assert result == expected
        mock_db.ml.list_model_outputs.assert_called_once_with("model-1")


@pytest.mark.unit
class TestListFullyLabeledModelOutputs:
    """Tests for ``list_fully_labeled_model_outputs``."""

    def test_filters_to_only_fully_labeled(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_model_outputs.return_value = [
            ModelOutput(output_id="a", output_index=0, fully_labeled=True, label="mood"),
            ModelOutput(output_id="b", output_index=1, fully_labeled=False),
            ModelOutput(output_id="c", output_index=2, fully_labeled=True, label="genre"),
        ]

        result = list_fully_labeled_model_outputs(mock_db, "model-1")

        assert result == [
            ModelOutput(output_id="a", output_index=0, fully_labeled=True, label="mood"),
            ModelOutput(output_id="c", output_index=2, fully_labeled=True, label="genre"),
        ]


@pytest.mark.unit
class TestEnsureModelOutputs:
    """Tests for ``ensure_model_outputs``."""

    def test_inserts_missing_output_and_preserves_domain_metadata(self) -> None:
        mock_db = MagicMock()
        output_key = hashlib.sha256(b"model-1:0").hexdigest()[:16]
        mock_db.ml.get_model_output.return_value = None
        mock_db.ml.list_model_outputs.return_value = [ModelOutput(output_id=output_key, output_index=0)]

        result = ensure_model_outputs(mock_db, model_id="model-1", output_count=1)

        assert result == [ModelOutput(output_id=output_key, output_index=0)]
        mock_db.ml.replace_model_output.assert_called_once_with(
            "model-1",
            output_key,
            output_index=0,
            label=None,
            fully_labeled=False,
        )

    def test_preserves_existing_label_and_fully_labeled_flag(self) -> None:
        mock_db = MagicMock()
        output_key = hashlib.sha256(b"model-1:0").hexdigest()[:16]
        existing = ModelOutput(output_id=output_key, output_index=0, label="existing", fully_labeled=True)
        mock_db.ml.get_model_output.return_value = existing
        mock_db.ml.list_model_outputs.return_value = [existing]

        result = ensure_model_outputs(mock_db, model_id="model-1", output_count=1)

        assert result == [existing]
        mock_db.ml.replace_model_output.assert_called_once_with(
            "model-1",
            output_key,
            output_index=0,
            label="existing",
            fully_labeled=True,
        )


@pytest.mark.unit
class TestUpdateModelOutputLabel:
    """Tests for ``update_model_output_label``."""

    def test_updates_existing_output(self) -> None:
        mock_db = MagicMock()
        existing = ModelOutput(output_id="output-1", output_index=7)
        mock_db.ml.get_model_output.return_value = existing

        update_model_output_label(mock_db, model_id="model-1", output_id="output-1", label="mood")

        mock_db.ml.replace_model_output.assert_called_once_with(
            "model-1",
            "output-1",
            output_index=7,
            label="mood",
            fully_labeled=True,
        )

    def test_ignores_missing_output(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_model_output.return_value = None

        update_model_output_label(mock_db, model_id="model-1", output_id="missing", label="mood")

        mock_db.ml.replace_model_output.assert_not_called()
