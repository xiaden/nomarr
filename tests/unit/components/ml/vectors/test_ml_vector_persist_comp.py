"""Tests for ``nomarr.components.ml.vectors.ml_vector_persist_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from nomarr.components.ml.vectors.ml_vector_persist_comp import persist_backbone_vector

PATCH_BASE = "nomarr.components.ml.vectors.ml_vector_persist_comp"


@pytest.mark.unit
class TestPersistBackboneVector:
    """Tests for ``persist_backbone_vector``."""

    def test_returns_elapsed_ms_on_success(self) -> None:
        """Returns elapsed milliseconds and persists the pooled vector on success."""
        mock_db = MagicMock()
        embeddings = np.ones((3, 128))
        pooled_vector = [0.25] * 128
        ops = MagicMock()

        with (
            patch(
                f"{PATCH_BASE}.internal_ms",
                side_effect=[MagicMock(value=1000), MagicMock(value=1050)],
            ) as mock_internal_ms,
            patch(
                f"{PATCH_BASE}.pool_embedding_for_storage",
                return_value=pooled_vector,
            ) as mock_pool_embedding,
            patch(f"{PATCH_BASE}.get_embedding_dimension", return_value=128) as mock_get_embedding_dimension,
            patch(f"{PATCH_BASE}.get_hot_namespace", return_value=ops) as mock_get_hot_namespace,
        ):
            result = persist_backbone_vector(
                db=mock_db,
                file_id="library_files/f1",
                backbone="effnet",
                embeddings_2d=embeddings,
                model_suite_hash="abc123",
                path="/music/f1.mp3",
                library_key="lib1",
            )

        assert result == 50
        mock_internal_ms.assert_called()
        mock_pool_embedding.assert_called_once()
        mock_get_embedding_dimension.assert_called_once()
        mock_get_hot_namespace.assert_called_once_with(mock_db, "effnet", "lib1")
        ops.upsert_vector.assert_called_once_with(
            file_id="library_files/f1",
            model_suite_hash="abc123",
            embed_dim=128,
            vector=pooled_vector,
            num_segments=embeddings.shape[0],
        )

    def test_returns_none_on_exception(self) -> None:
        """Returns None and logs a warning when persistence raises an exception."""
        mock_db = MagicMock()
        embeddings = np.ones((3, 128))

        with (
            patch(f"{PATCH_BASE}.internal_ms", return_value=MagicMock(value=1000)) as mock_internal_ms,
            patch(f"{PATCH_BASE}.pool_embedding_for_storage", return_value=[0.5] * 128) as mock_pool_embedding,
            patch(f"{PATCH_BASE}.get_embedding_dimension", return_value=128) as mock_get_embedding_dimension,
            patch(
                f"{PATCH_BASE}.get_hot_namespace",
                side_effect=RuntimeError("db error"),
            ) as mock_get_hot_namespace,
            patch(f"{PATCH_BASE}.logger.warning") as mock_logger_warning,
        ):
            result = persist_backbone_vector(
                db=mock_db,
                file_id="library_files/f1",
                backbone="effnet",
                embeddings_2d=embeddings,
                model_suite_hash="abc123",
                path="/music/f1.mp3",
                library_key="lib1",
            )

        assert result is None
        mock_internal_ms.assert_called_once_with()
        mock_pool_embedding.assert_called_once()
        mock_get_embedding_dimension.assert_called_once()
        mock_get_hot_namespace.assert_called_once_with(mock_db, "effnet", "lib1")
        mock_logger_warning.assert_called_once_with(
            "[processor] Failed to persist %s vector for %s",
            "effnet",
            "/music/f1.mp3",
            exc_info=True,
        )

    def test_passes_correct_args_to_upsert_vector(self) -> None:
        """Passes the expected keyword arguments to upsert_vector."""
        mock_db = MagicMock()
        embeddings = np.ones((3, 64))
        pooled_vector = [0.1] * 64
        ops = MagicMock()

        with (
            patch(
                f"{PATCH_BASE}.internal_ms",
                side_effect=[MagicMock(value=10), MagicMock(value=25)],
            ) as mock_internal_ms,
            patch(
                f"{PATCH_BASE}.pool_embedding_for_storage",
                return_value=pooled_vector,
            ) as mock_pool_embedding,
            patch(f"{PATCH_BASE}.get_embedding_dimension", return_value=64) as mock_get_embedding_dimension,
            patch(f"{PATCH_BASE}.get_hot_namespace", return_value=ops) as mock_get_hot_namespace,
        ):
            result = persist_backbone_vector(
                db=mock_db,
                file_id="library_files/f1",
                backbone="effnet",
                embeddings_2d=embeddings,
                model_suite_hash="abc123",
                path="/music/f1.mp3",
                library_key="lib1",
            )

        assert result == 15
        mock_internal_ms.assert_called()
        mock_pool_embedding.assert_called_once_with(embeddings)
        mock_get_embedding_dimension.assert_called_once_with(embeddings)
        mock_get_hot_namespace.assert_called_once_with(mock_db, "effnet", "lib1")
        ops.upsert_vector.assert_called_once_with(
            file_id="library_files/f1",
            model_suite_hash="abc123",
            embed_dim=64,
            vector=pooled_vector,
            num_segments=3,
        )
