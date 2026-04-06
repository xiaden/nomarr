"""Tests for ``nomarr.persistence.database.library_files_aql.stats``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.library_files_aql.stats import LibraryFilesStatsMixin


class _ConcreteStatsMixin(LibraryFilesStatsMixin):
    """Minimal concrete class for testing the mixin."""

    def __init__(self, db: MagicMock) -> None:
        self.db = db
        self.collection = MagicMock()
        self.parent_db = None


class TestCountFilesByTag:
    """Tests for ``LibraryFilesStatsMixin.count_files_by_tag``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_int_for_string_target_value(self) -> None:
        """String target values should use the exact-match branch and return an int."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([42])
        mixin = _ConcreteStatsMixin(mock_db)

        result = mixin.count_files_by_tag("genre", "rock")

        assert result == 42
        query = mock_db.aql.execute.call_args.args[0]
        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]
        assert "tag.value == @target_value" in query
        assert "IS_NUMBER(tag.value)" not in query
        assert bind_vars == {"tag_key": "genre", "target_value": "rock"}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_int_for_float_target_value(self) -> None:
        """Float target values should use the numeric branch and return an int."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([7])
        mixin = _ConcreteStatsMixin(mock_db)

        result = mixin.count_files_by_tag("nom:bpm", 120.5)

        assert result == 7
        query = mock_db.aql.execute.call_args.args[0]
        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]
        assert "IS_NUMBER(tag.value)" in query
        assert bind_vars == {"tag_key": "nom:bpm", "target_value": 120.5}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_treats_integer_target_value_as_numeric_branch(self) -> None:
        """Integers should follow the numeric branch rather than exact string matching."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([3])
        mixin = _ConcreteStatsMixin(mock_db)

        result = mixin.count_files_by_tag("nom:rating", 7)

        assert result == 3
        query = mock_db.aql.execute.call_args.args[0]
        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]
        assert "IS_NUMBER(tag.value)" in query
        assert bind_vars == {"tag_key": "nom:rating", "target_value": 7.0}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_treats_bool_target_value_as_string_branch(self) -> None:
        """Booleans are excluded from the numeric branch and should be stringified."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([5])
        mixin = _ConcreteStatsMixin(mock_db)

        result = mixin.count_files_by_tag("flag", True)

        assert result == 5
        query = mock_db.aql.execute.call_args.args[0]
        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]
        assert "tag.value == @target_value" in query
        assert "IS_NUMBER(tag.value)" not in query
        assert bind_vars == {"tag_key": "flag", "target_value": "True"}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_cursor_empty(self) -> None:
        """Empty cursor results should fall back to zero."""
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([])
        mixin = _ConcreteStatsMixin(mock_db)

        result = mixin.count_files_by_tag("genre", "rock")

        assert result == 0
