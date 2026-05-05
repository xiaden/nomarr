"""Tests for library-file inventory query helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.library.library_file_query_comp import list_all_file_ids
from nomarr.persistence.constructor.pagination import DEFAULT_LIMIT


class TestListAllFileIds:
    """Tests for list_all_file_ids()."""

    @pytest.mark.unit
    def test_returns_all_file_ids_without_limit(self) -> None:
        """Returns all file IDs when no limit is provided."""
        mock_db = MagicMock()
        mock_db.library_files.aggregate.return_value = [
            {"value": "library_files/1"},
            {"value": "library_files/2"},
        ]

        result = list_all_file_ids(mock_db)

        assert result == ["library_files/1", "library_files/2"]
        mock_db.library_files.aggregate.assert_called_once_with("_id", limit=DEFAULT_LIMIT)

    @pytest.mark.unit
    def test_uses_explicit_collect_limit_when_provided(self) -> None:
        """Uses the caller-provided aggregate limit when supplied."""
        mock_db = MagicMock()
        mock_db.library_files.aggregate.return_value = []

        list_all_file_ids(mock_db, limit=10)

        mock_db.library_files.aggregate.assert_called_once_with("_id", limit=10)

    @pytest.mark.unit
    def test_returns_empty_list_when_no_files(self) -> None:
        """Returns an empty list when no file IDs are found."""
        mock_db = MagicMock()
        mock_db.library_files.aggregate.return_value = []

        result = list_all_file_ids(mock_db)

        assert result == []
