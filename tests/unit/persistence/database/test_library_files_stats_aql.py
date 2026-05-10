"""Tests for library-file stats query helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.library_file_query_comp import count_files_by_tag


class TestCountFilesByTag:
    """Tests for ``count_files_by_tag``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_int_for_string_target_value(self) -> None:
        """String target values should use exact collection get lookups and return an int."""
        mock_db = MagicMock()
        mock_db.count_files_by_tag.return_value = 2

        result = count_files_by_tag(mock_db, "genre", "rock")

        assert result == 2
        mock_db.count_files_by_tag.assert_called_once_with("genre", "rock")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_int_for_float_target_value(self) -> None:
        """Float target values should use the numeric branch and return an int."""
        mock_db = MagicMock()
        mock_db.count_files_by_tag.return_value = 1

        result = count_files_by_tag(mock_db, "nom:bpm", 120.5)

        assert result == 1
        mock_db.count_files_by_tag.assert_called_once_with("nom:bpm", 120.5)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_treats_integer_target_value_as_numeric_branch(self) -> None:
        """Integers should follow the numeric branch rather than exact string matching."""
        mock_db = MagicMock()
        mock_db.count_files_by_tag.return_value = 1

        result = count_files_by_tag(mock_db, "nom:rating", 7)

        assert result == 1
        mock_db.count_files_by_tag.assert_called_once_with("nom:rating", 7)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_treats_bool_target_value_as_string_branch(self) -> None:
        """Booleans are excluded from the numeric branch and should be stringified."""
        mock_db = MagicMock()
        mock_db.count_files_by_tag.return_value = 1

        result = count_files_by_tag(mock_db, "flag", True)

        assert result == 1
        mock_db.count_files_by_tag.assert_called_once_with("flag", True)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_no_matching_tag_ids(self) -> None:
        """Missing matching tags should return zero."""
        mock_db = MagicMock()
        mock_db.count_files_by_tag.return_value = 0

        result = count_files_by_tag(mock_db, "genre", "rock")

        assert result == 0
        mock_db.count_files_by_tag.assert_called_once_with("genre", "rock")
