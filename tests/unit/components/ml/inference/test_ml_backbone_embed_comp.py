"""Tests for ``nomarr.components.ml.inference.ml_backbone_embed_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from nomarr.components.ml.inference.ml_backbone_embed_comp import compute_backbone_embeddings


def _make_model_mock(embedding: np.ndarray) -> MagicMock:
    """Create a mock backbone model that returns the given embedding."""
    model = MagicMock()
    model.run.return_value = embedding
    return model


@pytest.mark.unit
class TestComputeBackboneEmbeddings:
    def test_single_backbone_returns_embedding(self) -> None:
        expected_embedding = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
        model_mock = _make_model_mock(expected_embedding)

        cache = MagicMock()
        cache.backbones = {"effnet": model_mock}

        heads_by_backbone = {"effnet": [MagicMock()]}
        waveform = np.array([0.1, 0.2, 0.3], dtype=np.float32)

        result = compute_backbone_embeddings(cache, heads_by_backbone, waveform)

        assert len(result.embeddings) == 1
        assert result.embeddings[0].backbone == "effnet"
        np.testing.assert_array_equal(result.embeddings[0].embeddings, expected_embedding)
        assert result.errors == {}
        model_mock.run.assert_called_once()

    def test_parallel_computation_returns_all_backbones(self) -> None:
        """With 2+ backbones, the ThreadPoolExecutor path is used."""
        effnet_embedding = np.array([[1.0, 2.0]], dtype=np.float32)
        yamnet_embedding = np.array([[3.0, 4.0]], dtype=np.float32)

        effnet_mock = _make_model_mock(effnet_embedding)
        yamnet_mock = _make_model_mock(yamnet_embedding)

        cache = MagicMock()
        cache.backbones = {"effnet": effnet_mock, "yamnet": yamnet_mock}

        heads_by_backbone = {"effnet": [MagicMock()], "yamnet": [MagicMock()]}
        waveform = np.array([0.1, 0.2, 0.3], dtype=np.float32)

        result = compute_backbone_embeddings(cache, heads_by_backbone, waveform)

        assert len(result.embeddings) == 2
        backbone_names = {e.backbone for e in result.embeddings}
        assert backbone_names == {"effnet", "yamnet"}
        assert result.errors == {}
        # Parallel path should record wall time
        assert "emb_wall" in result.timings

    def test_backbone_error_is_recorded_in_errors(self) -> None:
        """Error from one backbone is recorded in errors dict, not raised."""
        failing_model = MagicMock()
        failing_model.run.side_effect = RuntimeError("session not loaded")

        working_embedding = np.array([[1.0, 2.0]], dtype=np.float32)
        working_model = _make_model_mock(working_embedding)

        cache = MagicMock()
        cache.backbones = {"failing": failing_model, "working": working_model}

        heads_by_backbone = {"failing": [MagicMock()], "working": [MagicMock()]}
        waveform = np.array([0.1, 0.2, 0.3], dtype=np.float32)

        result = compute_backbone_embeddings(cache, heads_by_backbone, waveform)

        assert "failing" in result.errors
        assert "session not loaded" in result.errors["failing"]
        # Working backbone should still succeed
        successful_backbones = {e.backbone for e in result.embeddings}
        assert "working" in successful_backbones
