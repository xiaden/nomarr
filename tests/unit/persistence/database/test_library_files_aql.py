"""Tests for explicit library-files AQL operations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.database.library_files_aql import LibraryFilesAqlOperations


@pytest.mark.unit
@pytest.mark.mocked
class TestLibraryFilesAqlOperations:
    def test_list_all_file_ids_uses_aql_and_normalizes_rows(self) -> None:
        ops = LibraryFilesAqlOperations(MagicMock())
        # Include a non-string row to verify id filtering behavior.
        with patch("nomarr.persistence.database.library_files_aql.execute", return_value=["library_files/1", 3]) as exec_mock:
            result = ops.list_all_file_ids(limit=10)

        assert result == ["library_files/1"]
        bind_vars = exec_mock.call_args.args[2]
        assert bind_vars["limit"] == 10

    def test_count_files_by_tag_string_target(self) -> None:
        ops = LibraryFilesAqlOperations(MagicMock())
        with patch("nomarr.persistence.database.library_files_aql.execute", return_value=[2]) as exec_mock:
            result = ops.count_files_by_tag("genre", "rock")

        assert result == 2
        bind_vars = exec_mock.call_args.args[2]
        assert bind_vars == {"tag_key": "genre", "tag_value": "rock"}

    def test_count_files_by_tag_numeric_target(self) -> None:
        ops = LibraryFilesAqlOperations(MagicMock())
        with patch("nomarr.persistence.database.library_files_aql.execute", return_value=[1]) as exec_mock:
            result = ops.count_files_by_tag("nom:bpm", 120.0)

        assert result == 1
        bind_vars = exec_mock.call_args.args[2]
        assert bind_vars == {"tag_key": "nom:bpm"}

    def test_get_tracks_for_matching_unscoped(self) -> None:
        ops = LibraryFilesAqlOperations(MagicMock())
        expected = [{"_id": "library_files/1", "isrc": "ABC123"}]
        with patch("nomarr.persistence.database.library_files_aql.execute", return_value=expected) as exec_mock:
            result = ops.get_tracks_for_matching()

        assert result == expected
        assert exec_mock.call_args.args[2] == {}

    def test_get_tracks_for_matching_scoped(self) -> None:
        ops = LibraryFilesAqlOperations(MagicMock())
        expected = [{"_id": "library_files/1", "isrc": "ABC123"}]
        with patch("nomarr.persistence.database.library_files_aql.execute", return_value=expected) as exec_mock:
            result = ops.get_tracks_for_matching(library_id="libraries/1")

        assert result == expected
        assert exec_mock.call_args.args[2] == {"library_id": "libraries/1"}
