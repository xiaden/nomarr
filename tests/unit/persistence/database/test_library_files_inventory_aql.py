"""Tests for nomarr.persistence.database.library_files_aql.inventory."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.library_files_aql.inventory import LibraryFilesInventoryMixin


class _ConcreteInventoryMixin(LibraryFilesInventoryMixin):
    """Minimal concrete class for testing the inventory mixin."""

    def __init__(self, db: MagicMock) -> None:
        self.db = db
        self.collection = MagicMock()
        self.parent_db = None


class TestListAllFileIds:
    """Tests for list_all_file_ids()."""

    @pytest.mark.unit
    def test_returns_all_file_ids_without_limit(self) -> None:
        """Returns all file IDs when no limit is provided."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter(["library_files/1", "library_files/2"])
        mixin = _ConcreteInventoryMixin(mock_db)

        result = mixin.list_all_file_ids()

        assert result == ["library_files/1", "library_files/2"]

    @pytest.mark.unit
    def test_query_includes_limit_when_provided(self) -> None:
        """Includes @limit in the query and bind vars when provided."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([])
        mixin = _ConcreteInventoryMixin(mock_db)

        mixin.list_all_file_ids(limit=10)

        query = mock_db.aql.execute.call_args.args[0]
        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]

        assert "@limit" in query
        assert bind_vars == {"limit": 10}

    @pytest.mark.unit
    def test_returns_empty_list_when_no_files(self) -> None:
        """Returns an empty list when no file IDs are found."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([])
        mixin = _ConcreteInventoryMixin(mock_db)

        result = mixin.list_all_file_ids()

        assert result == []
