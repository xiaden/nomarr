"""Tests for vector maintenance component helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.vectors.ml_vector_maintenance_comp import (
    backfill_genres,
    build_cold_vector_index,
    derive_embed_dim,
    drain_hot_to_cold,
    drop_cold_vector_index,
    has_vector_index,
    rebuild_cold_vector_index,
    verify_hot_empty,
)


class TestDrainHotToCold:
    """Tests for ``drain_hot_to_cold``."""

    @pytest.mark.unit
    def test_raises_when_hot_collection_missing(self) -> None:
        mock_db = MagicMock()
        hot_ops = mock_db.register_vectors_track_backbone.return_value
        hot_ops.move_collection.side_effect = ValueError(
            "Source collection 'vectors_track_hot__ast__lib1' does not exist"
        )

        with pytest.raises(ValueError, match="Source collection 'vectors_track_hot__ast__lib1' does not exist"):
            drain_hot_to_cold(mock_db, "ast", "lib1")

    @pytest.mark.unit
    def test_returns_zero_when_hot_collection_empty(self) -> None:
        mock_db = MagicMock()
        hot_ops = mock_db.register_vectors_track_backbone.return_value
        hot_ops.move_collection.return_value = 0
        mock_db.get_vectors_track_cold.side_effect = Exception("collection does not exist")

        result = drain_hot_to_cold(mock_db, "ast", "lib1")

        assert result == 0
        hot_ops.move_collection.assert_called_once_with("vectors_track_cold__ast__lib1")
        mock_db.get_vectors_track_cold.assert_called_once_with("ast", "lib1")

    @pytest.mark.unit
    def test_delegates_to_move_collection(self) -> None:
        mock_db = MagicMock()
        hot_ops = mock_db.register_vectors_track_backbone.return_value
        hot_ops.move_collection.return_value = 2

        drained = drain_hot_to_cold(mock_db, "ast", "lib1")

        assert drained == 2
        mock_db.register_vectors_track_backbone.assert_called_once_with("ast", "lib1")
        hot_ops.move_collection.assert_called_once_with("vectors_track_cold__ast__lib1")
        mock_db.get_vectors_track_cold.assert_called_once_with("ast", "lib1")


class TestBackfillGenres:
    """Tests for ``backfill_genres``."""

    @pytest.mark.unit
    def test_raises_when_cold_collection_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.get_vectors_track_cold.return_value.count.side_effect = RuntimeError("missing")

        with pytest.raises(ValueError, match="Cold collection 'vectors_track_cold__ast__lib1' does not exist"):
            backfill_genres(mock_db, "ast", "lib1")

    @pytest.mark.unit
    def test_returns_updated_count(self) -> None:
        mock_db = MagicMock()
        cold_ops = mock_db.get_vectors_track_cold.return_value
        cold_ops.count.return_value = 2
        cold_ops._id.collect.return_value = ["vectors_track_cold__ast__lib1/k1", "vectors_track_cold__ast__lib1/k2"]
        cold_ops.get.many.return_value = [
            {"_key": "k1", "file_id": "library_files/f1"},
            {"_key": "k2", "file_id": "library_files/f2"},
        ]
        # Batch genre fetch
        mock_db.song_has_tags._from.get.in_.return_value = [
            {"_from": "library_files/f1", "_to": "tags/g1"},
            {"_from": "library_files/f2", "_to": "tags/g2"},
            {"_from": "library_files/f2", "_to": "tags/g3"},
        ]
        mock_db.tags.get.many.return_value = [
            {"_id": "tags/g1", "rel": "genre", "value": "ambient"},
            {"_id": "tags/g2", "rel": "genre", "value": "jazz"},
            {"_id": "tags/g3", "rel": "genre", "value": "fusion"},
        ]

        result = backfill_genres(mock_db, "ast", "lib1")

        assert result == 2
        cold_ops.update_many.assert_called_once_with(
            [
                {"_key": "k1", "genres": ["ambient"]},
                {"_key": "k2", "genres": ["jazz", "fusion"]},
            ]
        )

    @pytest.mark.unit
    def test_returns_zero_when_cursor_empty(self) -> None:
        mock_db = MagicMock()
        cold_ops = mock_db.get_vectors_track_cold.return_value
        cold_ops.count.return_value = 0

        result = backfill_genres(mock_db, "ast", "lib1")

        assert result == 0
        cold_ops.update_many.assert_not_called()


class TestVerifyHotEmpty:
    """Tests for ``verify_hot_empty``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_when_hot_count_is_zero(self) -> None:
        mock_db = MagicMock()
        maintenance = mock_db.get_vectors_track_maintenance.return_value
        maintenance.get_stats.return_value = {"hot_count": 0}

        verify_hot_empty(mock_db, "ast", "lib1")

        mock_db.get_vectors_track_maintenance.assert_called_once_with("ast", "lib1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_when_hot_collection_not_empty(self) -> None:
        mock_db = MagicMock()
        maintenance = mock_db.get_vectors_track_maintenance.return_value
        maintenance.get_stats.return_value = {"hot_count": 3}

        with pytest.raises(RuntimeError, match="not empty after drain"):
            verify_hot_empty(mock_db, "ast", "lib1")


class TestDropColdVectorIndex:
    """Tests for ``drop_cold_vector_index``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_drop_index(self) -> None:
        mock_db = MagicMock()
        maintenance = mock_db.get_vectors_track_maintenance.return_value

        drop_cold_vector_index(mock_db, "ast", "lib1")

        maintenance.drop_index.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_swallows_value_error(self) -> None:
        mock_db = MagicMock()
        maintenance = mock_db.get_vectors_track_maintenance.return_value
        maintenance.drop_index.side_effect = ValueError("missing index")

        drop_cold_vector_index(mock_db, "ast", "lib1")

        maintenance.drop_index.assert_called_once_with()


class TestHasVectorIndex:
    """Tests for ``has_vector_index``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_true_when_index_exists(self) -> None:
        mock_db = MagicMock()
        maintenance = mock_db.get_vectors_track_maintenance.return_value
        maintenance.get_stats.return_value = {"index_exists": True}

        result = has_vector_index(mock_db, "ast", "lib1")

        assert result is True

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_index_absent(self) -> None:
        mock_db = MagicMock()
        maintenance = mock_db.get_vectors_track_maintenance.return_value
        maintenance.get_stats.return_value = {"index_exists": False}

        result = has_vector_index(mock_db, "ast", "lib1")

        assert result is False


class TestBuildColdVectorIndex:
    """Tests for ``build_cold_vector_index``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_build_index_with_params(self) -> None:
        mock_db = MagicMock()
        maintenance = mock_db.get_vectors_track_maintenance.return_value
        maintenance.get_stats.return_value = {"cold_count": 12}

        build_cold_vector_index(mock_db, "ast", "lib1", embed_dim=256, nlists=10)

        maintenance.build_index.assert_called_once_with(embed_dim=256, nlists=10)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_runtime_error_on_failure(self) -> None:
        mock_db = MagicMock()
        maintenance = mock_db.get_vectors_track_maintenance.return_value
        maintenance.get_stats.return_value = {"cold_count": 12}
        maintenance.build_index.side_effect = Exception("db error")

        with pytest.raises(RuntimeError, match="Vector index creation failed"):
            build_cold_vector_index(mock_db, "ast", "lib1", embed_dim=256, nlists=10)


class TestRebuildColdVectorIndex:
    """Tests for ``rebuild_cold_vector_index``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_rebuild_index(self) -> None:
        mock_db = MagicMock()
        maintenance = mock_db.get_vectors_track_maintenance.return_value

        rebuild_cold_vector_index(mock_db, "ast", "lib1", embed_dim=256, nlists=10)

        maintenance.rebuild_index.assert_called_once_with(embed_dim=256, nlists=10)


class TestDeriveEmbedDim:
    """Tests for ``derive_embed_dim``."""

    @pytest.mark.unit
    @pytest.mark.skip(reason="requires onnxruntime")
    def test_requires_onnxruntime(self) -> None:
        derive_embed_dim("/models", "ast")
