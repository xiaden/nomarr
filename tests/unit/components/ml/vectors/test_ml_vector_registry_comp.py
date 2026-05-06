"""Unit tests for the vector registry component."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.ml.vectors.ml_vector_registry_comp import (
    delete_vectors_by_file_id,
    delete_vectors_by_file_ids,
    get_cold_namespace,
    get_hot_namespace,
    get_maintenance_namespace,
)


class TestGetHotNamespace:
    """Tests for ``get_hot_namespace``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_hot_collection_and_returns_registered_namespace(self) -> None:
        db = MagicMock()
        hot_namespace = MagicMock()
        db.register.return_value = hot_namespace

        result = get_hot_namespace(db, "effnet", "lib1")

        assert result is hot_namespace
        db.register.assert_called_once_with("vectors_track_hot__effnet__lib1", "vectors_track_hot")


class TestGetColdNamespace:
    """Tests for ``get_cold_namespace``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_cold_collection_without_suffix(self) -> None:
        db = MagicMock()
        cold_namespace = MagicMock()
        db.register.return_value = cold_namespace

        result = get_cold_namespace(db, "effnet", "lib1")

        assert result is cold_namespace
        db.register.assert_called_once_with("vectors_track_cold__effnet__lib1", "vectors_track_cold")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_cold_collection_with_suffix(self) -> None:
        db = MagicMock()
        cold_namespace = MagicMock()
        db.register.return_value = cold_namespace

        result = get_cold_namespace(db, "effnet", "lib1", collection_suffix="staging")

        assert result is cold_namespace
        db.register.assert_called_once_with("vectors_track_cold__effnet__lib1__staging", "vectors_track_cold")


class TestGetMaintenanceNamespace:
    """Tests for ``get_maintenance_namespace``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_builds_maintenance_namespace_for_hot_and_cold_collections(self) -> None:
        db = MagicMock()
        db.db = MagicMock()
        maintenance_namespace = MagicMock()

        with patch(
            "nomarr.components.ml.vectors.ml_vector_registry_comp._VectorsTrackMaintenance",
            return_value=maintenance_namespace,
        ) as mock_namespace_ctor:
            result = get_maintenance_namespace(db, "effnet", "lib1")

        assert result is maintenance_namespace
        mock_namespace_ctor.assert_called_once_with(
            db.db,
            hot_collection_name="vectors_track_hot__effnet__lib1",
            cold_collection_name="vectors_track_cold__effnet__lib1",
        )


class TestDeleteVectorsByFileId:
    """Tests for ``delete_vectors_by_file_id``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_iterates_all_registered_vector_collections_and_executes_edge_cleanup(self) -> None:
        db = MagicMock()

        hot_namespace = MagicMock()
        hot_namespace.file_id.delete.return_value = 1
        cold_namespace = MagicMock()
        cold_namespace.file_id.delete.return_value = 2
        db._registered = {
            "vectors_track_hot__effnet__lib1": hot_namespace,
            "vectors_track_cold__effnet__lib1": cold_namespace,
        }
        db.db = MagicMock()

        deleted = delete_vectors_by_file_id(db, "library_files/7")

        assert deleted == 3
        hot_namespace.file_id.delete.assert_called_once_with("library_files/7")
        cold_namespace.file_id.delete.assert_called_once_with("library_files/7")
        db.db.aql.execute.assert_called_once()
        query = db.db.aql.execute.call_args.args[0]
        assert "FOR e IN file_has_vectors" in query
        assert db.db.aql.execute.call_args.kwargs["bind_vars"] == {"file_id": "library_files/7"}


class TestDeleteVectorsByFileIds:
    """Tests for ``delete_vectors_by_file_ids``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_for_empty_input(self) -> None:
        db = MagicMock()
        db._registered = {}
        db.db = MagicMock()

        deleted = delete_vectors_by_file_ids(db, [])

        assert deleted == 0
        db.db.aql.execute.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_iterates_every_namespace_for_each_file_id_and_executes_batch_cleanup(self) -> None:
        db = MagicMock()

        hot_namespace = MagicMock()
        hot_namespace.file_id.delete.side_effect = [1, 1]
        cold_namespace = MagicMock()
        cold_namespace.file_id.delete.side_effect = [2, 2]
        db._registered = {
            "vectors_track_hot__effnet__lib1": hot_namespace,
            "vectors_track_cold__effnet__lib1": cold_namespace,
        }
        db.db = MagicMock()

        deleted = delete_vectors_by_file_ids(db, ["library_files/1", "library_files/2"])

        assert deleted == 6
        assert hot_namespace.file_id.delete.call_args_list == [
            call("library_files/1"),
            call("library_files/2"),
        ]
        assert cold_namespace.file_id.delete.call_args_list == [
            call("library_files/1"),
            call("library_files/2"),
        ]
        db.db.aql.execute.assert_called_once()
        query = db.db.aql.execute.call_args.args[0]
        assert "FILTER e._from IN @file_ids" in query
        assert db.db.aql.execute.call_args.kwargs["bind_vars"] == {"file_ids": ["library_files/1", "library_files/2"]}
