"""Tests for vector maintenance component helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.vectors.ml_vector_maintenance_comp import (
    backfill_genres,
    derive_embed_dim,
)
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
            pytest.raises(ValueError, match="Cold collection 'vectors_track_cold__ast__lib1' does not exist"),
        ):
            backfill_genres(mock_db, "ast", "lib1")

        mock_get_cold.assert_called_once_with(mock_db, "ast", "lib1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_updated_count(self) -> None:
        mock_db = MagicMock()
        cold_ops = MagicMock()
        cold_ops.count.return_value = 2
        cold_ops.aggregate.return_value = [
            {"value": "vectors_track_cold__ast__lib1/k1"},
            {"value": "vectors_track_cold__ast__lib1/k2"},
        ]
        cold_ops.get.in_.return_value = [
            {"_id": "vectors_track_cold__ast__lib1/k1", "_key": "k1", "file_id": "library_files/f1"},
            {"_id": "vectors_track_cold__ast__lib1/k2", "_key": "k2", "file_id": "library_files/f2"},
        ]
        mock_db.library.list_genre_tags_for_files.return_value = [
            {"fid": "library_files/f1", "genre": "ambient", "tag_id": "tags/g1"},
            {"fid": "library_files/f2", "genre": "jazz", "tag_id": "tags/g2"},
            {"fid": "library_files/f2", "genre": "fusion", "tag_id": "tags/g3"},
        ]

        with patch(f"{PATCH_BASE}.get_cold_namespace", return_value=cold_ops) as mock_get_cold:
            result = backfill_genres(mock_db, "ast", "lib1")

        assert result == 2
        mock_get_cold.assert_called_once_with(mock_db, "ast", "lib1")
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
            "vectors_track_cold__ast__lib1/k1",
            "vectors_track_cold__ast__lib1/k2",
        ]
        cold_ops.get.in_.assert_called_once_with(field_arg, limit=None)
        mock_db.library.list_genre_tags_for_files.assert_called_once_with(["library_files/f1", "library_files/f2"])

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_cursor_empty(self) -> None:
        mock_db = MagicMock()
        cold_ops = MagicMock()
        cold_ops.count.return_value = 0

        with patch(f"{PATCH_BASE}.get_cold_namespace", return_value=cold_ops) as mock_get_cold:
            result = backfill_genres(mock_db, "ast", "lib1")

        assert result == 0
        mock_get_cold.assert_called_once_with(mock_db, "ast", "lib1")
        cold_ops.update_many.assert_not_called()


class TestDeriveEmbedDim:
    """Tests for ``derive_embed_dim``."""

    @pytest.mark.unit
    @pytest.mark.skip(reason="requires onnxruntime")
    def test_requires_onnxruntime(self) -> None:
        derive_embed_dim("/models", "ast")
