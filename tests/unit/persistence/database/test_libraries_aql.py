"""Tests for libraries_aql operations."""

from __future__ import annotations

import pytest

from nomarr.persistence.database.libraries_aql import list_all_library_keys


class TestListAllLibraryKeys:
    """Tests for list_all_library_keys()."""

    @pytest.mark.unit
    def test_returns_list_of_keys(self, mock_db) -> None:
        """Returns library document keys from the cursor."""
        mock_db.aql.execute.return_value = iter(["lib1", "lib2"])

        result = list_all_library_keys(mock_db)

        assert result == ["lib1", "lib2"]

    @pytest.mark.unit
    def test_returns_empty_list_when_no_libraries(self, mock_db) -> None:
        """Returns an empty list when no libraries exist."""
        mock_db.aql.execute.return_value = iter([])

        result = list_all_library_keys(mock_db)

        assert result == []
