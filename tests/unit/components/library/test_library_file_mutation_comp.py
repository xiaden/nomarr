"""Tests for nomarr.components.library.library_file_mutation_comp."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.library_file_mutation_comp import (
    bulk_delete_files,
    delete_library_file,
    upsert_batch,
)


class TestUpsertBatch:
    """Tests for batch library-file mutation writes."""

    @pytest.mark.unit
    def test_empty_input_returns_empty_list_without_db_calls(self) -> None:
        mock_db = MagicMock()

        result = upsert_batch(mock_db, [])

        assert result == []
        mock_db.library.upsert_files_batch.assert_not_called()
        mock_db.library.upsert_library_file_links_batch.assert_not_called()

    @pytest.mark.unit
    @patch("nomarr.components.library.library_file_mutation_comp.initialize_file_states_batch")
    @patch("nomarr.components.library.library_file_mutation_comp.get_existing_file_paths")
    def test_batch_upserts_docs_edges_and_initializes_only_new_paths(
        self,
        mock_get_existing_file_paths: MagicMock,
        mock_initialize_file_states_batch: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        mock_get_existing_file_paths.return_value = {"C:/music/existing.mp3"}
        mock_db.library.get_file_by_path.side_effect = [
            {"_id": "library_files/existing"},
            {"_id": "library_files/new"},
        ]
        file_docs: list[dict[str, Any]] = [
            {
                "library_id": "libraries/rock",
                "path": "C:/music/existing.mp3",
                "normalized_path": "existing.mp3",
                "file_size": 111,
                "modified_time": 1000,
            },
            {
                "library_id": "libraries/rock",
                "path": "C:/music/new.mp3",
                "normalized_path": "new.mp3",
                "file_size": 222,
                "modified_time": 2000,
            },
        ]

        result = upsert_batch(mock_db, file_docs)

        assert result == ["library_files/existing", "library_files/new"]
        mock_get_existing_file_paths.assert_called_once_with(
            mock_db,
            ["C:/music/existing.mp3", "C:/music/new.mp3"],
        )
        mock_db.library.upsert_files_batch.assert_called_once_with(
            [
                {
                    "path": "C:/music/existing.mp3",
                    "normalized_path": "existing.mp3",
                    "file_size": 111,
                    "modified_time": 1000,
                },
                {
                    "path": "C:/music/new.mp3",
                    "normalized_path": "new.mp3",
                    "file_size": 222,
                    "modified_time": 2000,
                },
            ]
        )
        assert mock_db.library.get_file_by_path.call_args_list == [
            call("C:/music/existing.mp3", "libraries/rock"),
            call("C:/music/new.mp3", "libraries/rock"),
        ]
        mock_db.library.upsert_library_file_links_batch.assert_called_once_with(
            [
                {"_from": "libraries/rock", "_to": "library_files/existing"},
                {"_from": "libraries/rock", "_to": "library_files/new"},
            ]
        )
        mock_initialize_file_states_batch.assert_called_once_with(
            mock_db,
            ["library_files/new"],
        )

    @pytest.mark.unit
    @patch("nomarr.components.library.library_file_mutation_comp.initialize_file_states_batch")
    @patch("nomarr.components.library.library_file_mutation_comp.get_existing_file_paths")
    def test_batch_requires_library_id_for_each_doc(
        self,
        mock_get_existing_file_paths: MagicMock,
        mock_initialize_file_states_batch: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        mock_get_existing_file_paths.return_value = set()
        file_docs: list[dict[str, Any]] = [
            {
                "library_id": None,
                "path": "C:/music/first.mp3",
                "normalized_path": "first.mp3",
                "file_size": 100,
                "modified_time": 1000,
            },
            {
                "library_id": "libraries/jazz",
                "path": "C:/music/second.mp3",
                "normalized_path": "second.mp3",
                "file_size": 200,
                "modified_time": 2000,
            },
        ]

        with pytest.raises(ValueError, match="library_id is required for upsert_batch"):
            upsert_batch(mock_db, file_docs)

        mock_db.library.upsert_files_batch.assert_called_once_with(
            [
                {
                    "path": "C:/music/first.mp3",
                    "normalized_path": "first.mp3",
                    "file_size": 100,
                    "modified_time": 1000,
                },
                {
                    "path": "C:/music/second.mp3",
                    "normalized_path": "second.mp3",
                    "file_size": 200,
                    "modified_time": 2000,
                },
            ]
        )
        mock_db.library.get_file_by_path.assert_not_called()
        mock_db.library.upsert_library_file_links_batch.assert_not_called()
        mock_initialize_file_states_batch.assert_not_called()


class TestDeleteLibraryFile:
    """Tests for single-file deletion cleanup."""

    @pytest.mark.unit
    def test_deletes_claims_state_tags_links_and_doc(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_library_ids_for_files.return_value = {
            "library_files/123": "libraries/rock",
        }
        mock_db.library.list_library_file_ids.return_value = [
            "library_files/123",
            "library_files/456",
        ]
        mock_db.ml.list_registered_vector_namespaces.return_value = {
            "vectors_mtg_jamendo_moodtheme": object(),
            "vectors_mtg_jamendo_genre": object(),
        }

        delete_library_file(mock_db, "library_files/123")

        mock_db.app.release_claim.assert_called_once_with("library_files/123")
        mock_db.library.delete_all_tags_for_file.assert_called_once_with("library_files/123")
        assert mock_db.ml.delete_vectors_for_file.call_args_list == [
            call("vectors_mtg_jamendo_moodtheme", "library_files/123"),
            call("vectors_mtg_jamendo_genre", "library_files/123"),
        ]
        mock_db.app.delete_file_state_edges.assert_called_once_with(["library_files/123"])
        mock_db.library.delete_all_file_links_for_library.assert_called_once_with("libraries/rock")
        mock_db.library.upsert_library_file_links_batch.assert_called_once_with(
            [{"_from": "libraries/rock", "_to": "library_files/456"}]
        )
        mock_db.library.delete_file.assert_called_once_with("library_files/123")

    @pytest.mark.unit
    @patch("nomarr.components.library.library_file_mutation_comp._delete_library_files")
    def test_resolves_path_before_delete(
        self,
        mock_delete_library_files: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        mock_db.library.list_libraries.return_value = [{"_id": "libraries/rock"}]
        mock_db.library.get_file_by_path.return_value = {"_id": "library_files/resolved"}

        delete_library_file(mock_db, "C:/music/song.mp3")

        mock_db.library.get_file_by_path.assert_called_once_with("C:/music/song.mp3", "libraries/rock")
        mock_delete_library_files.assert_called_once_with(mock_db, ["library_files/resolved"])


class TestBulkDeleteFiles:
    """Tests for bulk deletion cleanup."""

    @pytest.mark.unit
    def test_bulk_delete_resolves_unscoped_paths_and_rewrites_links_per_library(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_file_by_path_unscoped.side_effect = [
            {"_id": "library_files/a"},
            None,
            {"_id": "library_files/c"},
        ]
        mock_db.library.get_library_ids_for_files.return_value = {
            "library_files/a": "libraries/rock",
            "library_files/c": "libraries/jazz",
        }
        mock_db.library.list_library_file_ids.side_effect = [
            ["library_files/c", "library_files/d"],
            ["library_files/a", "library_files/b"],
        ]
        mock_db.ml.list_registered_vector_namespaces.return_value = {
            "vectors_mtg_jamendo_moodtheme": object(),
            "vectors_mtg_jamendo_genre": object(),
        }

        result = bulk_delete_files(mock_db, ["C:/music/a.mp3", "C:/music/missing.mp3", "C:/music/c.mp3"])

        assert result == 2
        assert mock_db.library.get_file_by_path_unscoped.call_args_list == [
            call("C:/music/a.mp3"),
            call("C:/music/missing.mp3"),
            call("C:/music/c.mp3"),
        ]
        assert mock_db.app.release_claim.call_args_list == [
            call("library_files/a"),
            call("library_files/c"),
        ]
        assert mock_db.library.delete_all_tags_for_file.call_args_list == [
            call("library_files/a"),
            call("library_files/c"),
        ]
        assert mock_db.ml.delete_vectors_for_file.call_args_list == [
            call("vectors_mtg_jamendo_moodtheme", "library_files/a"),
            call("vectors_mtg_jamendo_genre", "library_files/a"),
            call("vectors_mtg_jamendo_moodtheme", "library_files/c"),
            call("vectors_mtg_jamendo_genre", "library_files/c"),
        ]
        mock_db.app.delete_file_state_edges.assert_called_once_with(
            [
                "library_files/a",
                "library_files/c",
            ]
        )
        assert mock_db.library.delete_all_file_links_for_library.call_args_list == [
            call("libraries/jazz"),
            call("libraries/rock"),
        ]
        assert mock_db.library.upsert_library_file_links_batch.call_args_list == [
            call([{"_from": "libraries/jazz", "_to": "library_files/d"}]),
            call([{"_from": "libraries/rock", "_to": "library_files/b"}]),
        ]
        assert mock_db.library.delete_file.call_args_list == [
            call("library_files/a"),
            call("library_files/c"),
        ]
