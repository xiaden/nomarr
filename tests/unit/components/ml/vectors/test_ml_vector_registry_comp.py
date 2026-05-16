"""Unit tests for the vector registry component."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.vectors.ml_vector_registry_comp import (
    delete_vectors_by_file_id,
    delete_vectors_by_file_ids,
    get_cold_namespace,
    get_hot_namespace,
)


class TestGetHotNamespace:
    """Tests for ``get_hot_namespace``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_hot_collection_and_returns_registered_namespace(self) -> None:
        db = MagicMock()
        hot_namespace = MagicMock()
        db.ml.add_vector_collection.return_value = hot_namespace

        result = get_hot_namespace(db, "effnet", "lib1")

        assert result is hot_namespace
        db.ml.add_vector_collection.assert_called_once_with("vectors_track_hot__effnet__lib1", "vectors_track_hot")


class TestGetColdNamespace:
    """Tests for ``get_cold_namespace``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_cold_collection_without_suffix(self) -> None:
        db = MagicMock()
        cold_namespace = MagicMock()
        db.ml.add_vector_collection.return_value = cold_namespace

        result = get_cold_namespace(db, "effnet", "lib1")

        assert result is cold_namespace
        db.ml.add_vector_collection.assert_called_once_with("vectors_track_cold__effnet__lib1", "vectors_track_cold")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_cold_collection_with_suffix(self) -> None:
        db = MagicMock()
        cold_namespace = MagicMock()
        db.ml.add_vector_collection.return_value = cold_namespace

        result = get_cold_namespace(db, "effnet", "lib1", collection_suffix="staging")

        assert result is cold_namespace
        db.ml.add_vector_collection.assert_called_once_with(
            "vectors_track_cold__effnet__lib1__staging", "vectors_track_cold"
        )


class TestDeleteVectorsByFileId:
    """Tests for ``delete_vectors_by_file_id``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_iterates_all_registered_vector_collections_and_executes_edge_cleanup(self) -> None:
        db = MagicMock()

        db.ml.list_vector_namespaces.return_value = {
            "vectors_track_hot__effnet__lib1": MagicMock(),
            "vectors_track_cold__effnet__lib1": MagicMock(),
        }
        db.ml.list_file_vectors.side_effect = [
            [{"_id": "vectors_track_hot__effnet__lib1/doc-1"}],
            [
                {"_id": "vectors_track_cold__effnet__lib1/doc-1"},
                {"_id": "vectors_track_cold__effnet__lib1/doc-2"},
            ],
        ]

        deleted = delete_vectors_by_file_id(db, "library_files/7")

        assert deleted == 3
        db.ml.list_vector_namespaces.assert_called_once_with()
        db.ml.list_file_vectors.assert_any_call("vectors_track_hot__effnet__lib1", "library_files/7")
        db.ml.list_file_vectors.assert_any_call("vectors_track_cold__effnet__lib1", "library_files/7")
        db.ml.remove_file_vectors.assert_any_call("vectors_track_hot__effnet__lib1", "library_files/7")
        db.ml.remove_file_vectors.assert_any_call("vectors_track_cold__effnet__lib1", "library_files/7")


class TestDeleteVectorsByFileIds:
    """Tests for ``delete_vectors_by_file_ids``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_for_empty_input(self) -> None:
        db = MagicMock()

        deleted = delete_vectors_by_file_ids(db, [])

        assert deleted == 0
        db.ml.list_vector_namespaces.assert_not_called()
        db.ml.remove_vectors_for_files.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_iterates_every_namespace_for_each_file_id_and_executes_batch_cleanup(self) -> None:
        db = MagicMock()

        db.ml.list_vector_namespaces.return_value = {
            "vectors_track_hot__effnet__lib1": MagicMock(),
            "vectors_track_cold__effnet__lib1": MagicMock(),
        }
        db.ml.list_file_vectors.side_effect = [
            [{"_id": "vectors_track_hot__effnet__lib1/doc-1"}],
            [{"_id": "vectors_track_hot__effnet__lib1/doc-2"}],
            [{"_id": "vectors_track_cold__effnet__lib1/doc-1"}],
            [
                {"_id": "vectors_track_cold__effnet__lib1/doc-2"},
                {"_id": "vectors_track_cold__effnet__lib1/doc-3"},
                {"_id": "vectors_track_cold__effnet__lib1/doc-4"},
            ],
        ]

        deleted = delete_vectors_by_file_ids(db, ["library_files/1", "library_files/2"])

        assert deleted == 6
        db.ml.list_vector_namespaces.assert_called_once_with()
        assert db.ml.list_file_vectors.call_count == 4
        db.ml.remove_vectors_for_files.assert_any_call(
            "vectors_track_hot__effnet__lib1", ["library_files/1", "library_files/2"]
        )
        db.ml.remove_vectors_for_files.assert_any_call(
            "vectors_track_cold__effnet__lib1", ["library_files/1", "library_files/2"]
        )
