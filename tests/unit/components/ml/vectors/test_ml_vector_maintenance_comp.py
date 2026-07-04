"""Tests for vector maintenance component helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.vectors.ml_vector_maintenance_comp import (
    backfill_genres,
    derive_embed_dim,
)
from nomarr.persistence.schema import CollectionNames
from nomarr.persistence.schema_types import Field

PATCH_BASE = "nomarr.components.ml.vectors.ml_vector_maintenance_comp"


class TestBackfillGenres:
    """Tests for ``backfill_genres``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_when_cold_collection_missing(self) -> None:
        mock_db = MagicMock()
        cold_ops = MagicMock()
        cold_ops.count.side_effect = RuntimeError("missing")

        with (
            patch(f"{PATCH_BASE}.get_cold_namespace", return_value=cold_ops) as mock_get_cold,
            pytest.raises(ValueError, match="Cold collection 'vectors_track_cold__ast' does not exist"),
        ):
            backfill_genres(mock_db, "ast")

        mock_get_cold.assert_called_once_with(mock_db, "ast")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_updated_count(self) -> None:
        mock_db = MagicMock()
        cold_ops = MagicMock()
        cold_ops.count.return_value = 2
        cold_ops.aggregate.return_value = [
            {"value": "vectors_track_cold__ast/k1"},
            {"value": "vectors_track_cold__ast/k2"},
        ]
        cold_ops.get.in_.return_value = [
            {
                "_id": "vectors_track_cold__ast/k1",
                "_key": "k1",
                "file_id": f"{CollectionNames.LIBRARY_FILES.value}/f1",
            },
            {
                "_id": "vectors_track_cold__ast/k2",
                "_key": "k2",
                "file_id": f"{CollectionNames.LIBRARY_FILES.value}/f2",
            },
        ]
        mock_db.library.list_genre_tags_for_files.return_value = [
            {"fid": f"{CollectionNames.LIBRARY_FILES.value}/f1", "genre": "ambient", "tag_id": "tags/g1"},
            {"fid": f"{CollectionNames.LIBRARY_FILES.value}/f2", "genre": "jazz", "tag_id": "tags/g2"},
            {"fid": f"{CollectionNames.LIBRARY_FILES.value}/f2", "genre": "fusion", "tag_id": "tags/g3"},
        ]

        with patch(f"{PATCH_BASE}.get_cold_namespace", return_value=cold_ops) as mock_get_cold:
            result = backfill_genres(mock_db, "ast")

        assert result == 2
        mock_get_cold.assert_called_once_with(mock_db, "ast")
        cold_ops.update_many.assert_called_once_with(
            [
                {"_key": "k1", "genres": ["ambient"]},
                {"_key": "k2", "genres": ["jazz", "fusion"]},
            ]
        )
        field_arg = cold_ops.get.in_.call_args.args[0]
        assert isinstance(field_arg, Field)
        assert field_arg.name == "_id"
        assert field_arg.value == [
            "vectors_track_cold__ast/k1",
            "vectors_track_cold__ast/k2",
        ]
        cold_ops.get.in_.assert_called_once_with(field_arg, limit=None)
        mock_db.library.list_genre_tags_for_files.assert_called_once_with(
            [f"{CollectionNames.LIBRARY_FILES.value}/f1", f"{CollectionNames.LIBRARY_FILES.value}/f2"]
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_cursor_empty(self) -> None:
        mock_db = MagicMock()
        cold_ops = MagicMock()
        cold_ops.count.return_value = 0

        with patch(f"{PATCH_BASE}.get_cold_namespace", return_value=cold_ops) as mock_get_cold:
            result = backfill_genres(mock_db, "ast")

        assert result == 0
        mock_get_cold.assert_called_once_with(mock_db, "ast")
        cold_ops.update_many.assert_not_called()


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
