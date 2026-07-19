"""Tests for vector maintenance component helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.vectors.ml_vector_maintenance_comp import (
    backfill_genres,
    derive_embed_dim,
)

PATCH_BASE = "nomarr.components.ml.vectors.ml_vector_maintenance_comp"


class TestBackfillGenres:
    """Tests for ``backfill_genres`` — delegates to ``db.ml.backfill_genres``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_count_from_facade(self) -> None:
        """backfill_genres should return the count from db.ml.backfill_genres."""
        mock_db = MagicMock()
        mock_db.ml.backfill_genres = MagicMock(return_value=42)

        result = backfill_genres(mock_db, "ast")

        assert result == 42
        mock_db.ml.backfill_genres.assert_called_once_with("ast")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_no_embeddings_need_backfill(self) -> None:
        """Zero-count pass-through when no embeddings need genre backfill."""
        mock_db = MagicMock()
        mock_db.ml.backfill_genres = MagicMock(return_value=0)

        result = backfill_genres(mock_db, "ast")

        assert result == 0
        mock_db.ml.backfill_genres.assert_called_once_with("ast")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_propagates_exception_from_facade(self) -> None:
        """Exceptions from the facade should propagate to the caller."""
        mock_db = MagicMock()
        mock_db.ml.backfill_genres = MagicMock(side_effect=RuntimeError("DB connection lost"))

        with pytest.raises(RuntimeError, match="DB connection lost"):
            backfill_genres(mock_db, "ast")


class TestDeriveEmbedDim:
    """Tests for ``derive_embed_dim``.

    Because ``onnxruntime`` may not be installed in every test environment,
    the happy-path is exercised with mocks, not a real ONNX session.
    """

    PATCH_BASE = f"{PATCH_BASE}"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_value_error_when_embedding_graph_not_found(self) -> None:
        """When _resolve_embedding_graph returns None, raises ValueError."""
        with (
            patch(f"{self.PATCH_BASE}._resolve_embedding_graph", return_value=None),
            pytest.raises(ValueError, match="No embedding graph found"),
        ):
            derive_embed_dim("/fake/models", "nonexistent")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_dim_when_onnx_session_has_embeddings_output(self) -> None:
        """Valid ONNX session with 'embeddings' output returns its last dimension."""
        mock_session = MagicMock()
        mock_output = MagicMock()
        mock_output.name = "embeddings"
        mock_output.shape = [1, 1280]
        mock_session.get_outputs.return_value = [mock_output]

        mock_ort = MagicMock()
        mock_ort.InferenceSession.return_value = mock_session

        with (
            patch(f"{self.PATCH_BASE}._resolve_embedding_graph", return_value="/fake/backbone.onnx"),
            patch.dict("sys.modules", {"onnxruntime": mock_ort}),
        ):
            result = derive_embed_dim("/fake/models", "ast")

        assert result == 1280
        mock_ort.InferenceSession.assert_called_once_with("/fake/backbone.onnx", providers=["CPUExecutionProvider"])

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_value_error_when_onnx_session_fails(self) -> None:
        """When InferenceSession raises, it's wrapped in a ValueError."""
        mock_ort = MagicMock()
        mock_ort.InferenceSession.side_effect = RuntimeError("ONNX load failed")

        with (
            patch(f"{self.PATCH_BASE}._resolve_embedding_graph", return_value="/fake/backbone.onnx"),
            patch.dict("sys.modules", {"onnxruntime": mock_ort}),
            pytest.raises(ValueError, match="Failed to probe embedding graph"),
        ):
            derive_embed_dim("/fake/models", "ast")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_value_error_when_no_embeddings_output_found(self) -> None:
        """When ONNX session has no output named 'embeddings', raises ValueError."""
        mock_session = MagicMock()
        mock_output = MagicMock()
        mock_output.name = "logits"
        mock_output.shape = [1, 50]
        mock_session.get_outputs.return_value = [mock_output]

        mock_ort = MagicMock()
        mock_ort.InferenceSession.return_value = mock_session

        with (
            patch(f"{self.PATCH_BASE}._resolve_embedding_graph", return_value="/fake/backbone.onnx"),
            patch.dict("sys.modules", {"onnxruntime": mock_ort}),
            pytest.raises(ValueError, match="Cannot determine embed_dim"),
        ):
            derive_embed_dim("/fake/models", "ast")
