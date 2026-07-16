"""Tests for ``nomarr.components.ml.vectors.ml_vector_persist_comp``."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from nomarr.components.ml.vectors.ml_vector_persist_comp import persist_backbone_vector, upsert_hot_track_vector

PATCH_BASE = "nomarr.components.ml.vectors.ml_vector_persist_comp"


@pytest.mark.unit
class TestUpsertHotTrackVector:
    """Tests for ``upsert_hot_track_vector``."""

    async def test_replaces_file_vectors_and_reloads_vector_id(self) -> None:
        """Writes the vector document through normalized file-vector methods and reloads its id."""
        mock_db = AsyncMock()
        expected_key = hashlib.sha1(b"1|abc123").hexdigest()
        mock_db.ml.list_file_vectors.return_value = [
            {
                "id": "vectors_track_hot__effnet/vector-doc",
                "_key": expected_key,
            }
        ]

        with patch(f"{PATCH_BASE}.internal_ms", return_value=MagicMock(value=1234)):
            vector_id = await upsert_hot_track_vector(
                db=mock_db,
                file_id=1,
                backbone="effnet",
                model_suite_hash="abc123",
                embed_dim=2,
                vector=[3.0, 4.0],
                num_segments=7,
            )

        expected_doc = {
            "_key": expected_key,
            "file_id": 1,
            "model_suite_hash": "abc123",
            "embed_dim": 2,
            "vector": [3.0, 4.0],
            "vector_n": [0.6, 0.8],
            "num_segments": 7,
            "created_at": 1234,
        }

        assert vector_id == "vectors_track_hot__effnet/vector-doc"
        mock_db.ml.replace_file_vectors.assert_called_once_with(
            "vectors_track_hot__effnet",
            1,
            [expected_doc],
        )
        mock_db.ml.list_file_vectors.assert_called_once_with(
            "vectors_track_hot__effnet",
            1,
        )


@pytest.mark.unit
class TestPersistBackboneVector:
    """Tests for ``persist_backbone_vector``."""

    async def test_returns_elapsed_ms_on_success(self) -> None:
        """Returns elapsed milliseconds and persists the pooled vector on success."""
        mock_db = AsyncMock()
        embeddings = np.ones((3, 128))
        pooled_vector = [0.25] * 128

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
            patch(
                f"{PATCH_BASE}.upsert_hot_track_vector",
                return_value="vectors_track_hot__effnet/vector-doc",
            ) as mock_upsert_hot_track_vector,
        ):
            result = await persist_backbone_vector(
                db=mock_db,
                file_id=1,
                backbone="effnet",
                embeddings_2d=embeddings,
                model_suite_hash="abc123",
                path="/music/f1.mp3",
            )

        assert result == 50
        mock_internal_ms.assert_called()
        mock_pool_embedding.assert_called_once()
        mock_get_embedding_dimension.assert_called_once()
        mock_upsert_hot_track_vector.assert_called_once_with(
            db=mock_db,
            file_id=1,
            backbone="effnet",
            model_suite_hash="abc123",
            embed_dim=128,
            vector=pooled_vector,
            num_segments=embeddings.shape[0],
        )

    async def test_returns_none_on_exception(self) -> None:
        """Returns None and logs a warning when persistence raises an exception."""
        mock_db = AsyncMock()
        embeddings = np.ones((3, 128))

        with (
            patch(f"{PATCH_BASE}.internal_ms", return_value=MagicMock(value=1000)) as mock_internal_ms,
            patch(f"{PATCH_BASE}.pool_embedding_for_storage", return_value=[0.5] * 128) as mock_pool_embedding,
            patch(f"{PATCH_BASE}.get_embedding_dimension", return_value=128) as mock_get_embedding_dimension,
            patch(
                f"{PATCH_BASE}.upsert_hot_track_vector",
                side_effect=RuntimeError("db error"),
            ) as mock_upsert_hot_track_vector,
            patch(f"{PATCH_BASE}.logger.warning") as mock_logger_warning,
        ):
            result = await persist_backbone_vector(
                db=mock_db,
                file_id=1,
                backbone="effnet",
                embeddings_2d=embeddings,
                model_suite_hash="abc123",
                path="/music/f1.mp3",
            )

        assert result is None
        mock_internal_ms.assert_called_once_with()
        mock_pool_embedding.assert_called_once()
        mock_get_embedding_dimension.assert_called_once()
        mock_upsert_hot_track_vector.assert_called_once_with(
            db=mock_db,
            file_id=1,
            backbone="effnet",
            model_suite_hash="abc123",
            embed_dim=128,
            vector=[0.5] * 128,
            num_segments=embeddings.shape[0],
        )
        mock_logger_warning.assert_called_once_with(
            "[vectors] Failed to persist %s vector for %s",
            "effnet",
            "/music/f1.mp3",
            exc_info=True,
        )

    async def test_passes_correct_args_to_upsert_vector(self) -> None:
        """Passes the expected keyword arguments to the component-owned hot upsert seam."""
        mock_db = AsyncMock()
        embeddings = np.ones((3, 64))
        pooled_vector = [0.1] * 64

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
            patch(
                f"{PATCH_BASE}.upsert_hot_track_vector",
                return_value="vectors_track_hot__effnet/vector-doc",
            ) as mock_upsert_hot_track_vector,
        ):
            result = await persist_backbone_vector(
                db=mock_db,
                file_id=f"{'library_files'}/f1",
                backbone="effnet",
                embeddings_2d=embeddings,
                model_suite_hash="abc123",
                path="/music/f1.mp3",
                # library_key removed per ADR-036
            )

        assert result == 15
        mock_internal_ms.assert_called()
        mock_pool_embedding.assert_called_once_with(embeddings)
        mock_get_embedding_dimension.assert_called_once_with(embeddings)
        mock_upsert_hot_track_vector.assert_called_once_with(
            db=mock_db,
            file_id=f"{'library_files'}/f1",
            backbone="effnet",
            model_suite_hash="abc123",
            embed_dim=64,
            vector=pooled_vector,
            num_segments=3,
        )
