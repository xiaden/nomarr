"""Unit tests for the vector registry component."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.vectors.ml_vector_registry_comp import (
    delete_vectors_by_song_id,
    delete_vectors_by_song_ids,
)


def _make_db() -> MagicMock:
    """Create a mock Database with sync ml methods configured."""
    db = MagicMock()
    db.ml.list_vector_collection_names = MagicMock()
    db.ml.list_song_vectors = MagicMock()
    db.ml.remove_song_vectors = MagicMock()
    db.ml.remove_vectors_for_songs = MagicMock()
    return db


@pytest.mark.unit
class TestDeleteVectorsBySongId:
    """Tests for ``delete_vectors_by_song_id``."""

    @pytest.mark.mocked
    def test_iterates_all_registered_vector_collections_and_executes_edge_cleanup(self) -> None:
        db = _make_db()

        db.ml.list_vector_collection_names.return_value = [
            "vectors_track_hot__effnet",
            "vectors_track_cold__effnet",
        ]
        db.ml.list_song_vectors.side_effect = [
            [{"_id": "vectors_track_hot__effnet/doc-1"}],
            [
                {"_id": "vectors_track_cold__effnet/doc-1"},
                {"_id": "vectors_track_cold__effnet/doc-2"},
            ],
        ]

        deleted = delete_vectors_by_song_id(db, "7")

        assert deleted == 3
        db.ml.list_vector_collection_names.assert_called_once_with()
        db.ml.list_song_vectors.assert_any_call("vectors_track_hot__effnet", 7)
        db.ml.list_song_vectors.assert_any_call("vectors_track_cold__effnet", 7)
        db.ml.remove_song_vectors.assert_any_call("vectors_track_hot__effnet", 7)
        db.ml.remove_song_vectors.assert_any_call("vectors_track_cold__effnet", 7)


@pytest.mark.unit
class TestDeleteVectorsBySongIds:
    """Tests for ``delete_vectors_by_song_ids``."""

    @pytest.mark.mocked
    def test_returns_zero_for_empty_input(self) -> None:
        db = _make_db()

        deleted = delete_vectors_by_song_ids(db, [])

        assert deleted == 0
        db.ml.list_vector_collection_names.assert_not_called()
        db.ml.remove_vectors_for_songs.assert_not_called()

    @pytest.mark.mocked
    def test_iterates_every_namespace_for_each_song_id_and_executes_batch_cleanup(self) -> None:
        db = _make_db()

        db.ml.list_vector_collection_names.return_value = [
            "vectors_track_hot__effnet",
            "vectors_track_cold__effnet",
        ]
        db.ml.list_song_vectors.side_effect = [
            [{"_id": "vectors_track_hot__effnet/doc-1"}],
            [{"_id": "vectors_track_hot__effnet/doc-2"}],
            [{"_id": "vectors_track_cold__effnet/doc-1"}],
            [
                {"_id": "vectors_track_cold__effnet/doc-2"},
                {"_id": "vectors_track_cold__effnet/doc-3"},
                {"_id": "vectors_track_cold__effnet/doc-4"},
            ],
        ]

        deleted = delete_vectors_by_song_ids(db, ["1", "2"])

        assert deleted == 6
        db.ml.list_vector_collection_names.assert_called_once_with()
        assert db.ml.list_song_vectors.call_count == 4
        db.ml.remove_vectors_for_songs.assert_any_call(
            "vectors_track_hot__effnet",
            [1, 2],
        )
        db.ml.remove_vectors_for_songs.assert_any_call(
            "vectors_track_cold__effnet",
            [1, 2],
        )
