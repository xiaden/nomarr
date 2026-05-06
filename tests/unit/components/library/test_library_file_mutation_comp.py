"""Tests for nomarr.components.library.library_file_mutation_comp."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_file_mutation_comp import upsert_batch


class TestUpsertBatch:
    """Tests for batch library-file mutation writes."""

    @pytest.mark.unit
    def test_empty_input_returns_empty_list_without_db_calls(self) -> None:
        mock_db = MagicMock()

        result = upsert_batch(mock_db, [])

        assert result == []
        mock_db.library_files.upsert_batch.assert_not_called()
        mock_db.library_contains_file.upsert_batch.assert_not_called()

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
        mock_db.library_files.upsert_batch.return_value = [
            "library_files/existing",
            "library_files/new",
        ]
        file_docs = [
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
        mock_db.library_files.upsert_batch.assert_called_once_with(
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
            ],
            match_fields="path",
        )
        mock_db.library_contains_file.upsert_batch.assert_called_once_with(
            [
                {"_from": "libraries/rock", "_to": "library_files/existing"},
                {"_from": "libraries/rock", "_to": "library_files/new"},
            ],
            match_fields=["_from", "_to"],
        )
        mock_initialize_file_states_batch.assert_called_once_with(
            mock_db,
            ["library_files/new"],
        )

    @pytest.mark.unit
    @patch("nomarr.components.library.library_file_mutation_comp.initialize_file_states_batch")
    @patch("nomarr.components.library.library_file_mutation_comp.get_existing_file_paths")
    def test_skips_edge_batch_for_missing_library_ids_but_preserves_result_order(
        self,
        mock_get_existing_file_paths: MagicMock,
        mock_initialize_file_states_batch: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        mock_get_existing_file_paths.return_value = set()
        mock_db.library_files.upsert_batch.return_value = [
            "library_files/first",
            "library_files/second",
        ]
        file_docs = [
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

        result = upsert_batch(mock_db, file_docs)

        assert result == ["library_files/first", "library_files/second"]
        mock_db.library_contains_file.upsert_batch.assert_called_once_with(
            [{"_from": "libraries/jazz", "_to": "library_files/second"}],
            match_fields=["_from", "_to"],
        )
        mock_initialize_file_states_batch.assert_called_once_with(
            mock_db,
            ["library_files/first", "library_files/second"],
        )
