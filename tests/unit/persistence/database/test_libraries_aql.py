"""Tests for explicit libraries AQL operations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.database.libraries_aql import LibrariesAqlOperations


@pytest.mark.unit
@pytest.mark.mocked
class TestLibrariesAqlOperations:
    def test_insert_library_returns_id(self) -> None:
        ops = LibrariesAqlOperations(MagicMock())
        with patch("nomarr.persistence.database.libraries_aql.execute", return_value=["libraries/1"]):
            assert ops.insert_library({"name": "Main"}) == "libraries/1"

    def test_insert_library_raises_when_no_id_is_returned(self) -> None:
        ops = LibrariesAqlOperations(MagicMock())
        with (
            patch("nomarr.persistence.database.libraries_aql.execute", return_value=[]),
            pytest.raises(RuntimeError, match="Failed to insert library document"),
        ):
            ops.insert_library({"name": "Main"})

    def test_get_library_by_id_returns_dict_or_none(self) -> None:
        ops = LibrariesAqlOperations(MagicMock())
        with patch("nomarr.persistence.database.libraries_aql.execute", return_value=[{"_id": "libraries/1"}]):
            assert ops.get_library_by_id("libraries/1") == {"_id": "libraries/1"}
        with patch("nomarr.persistence.database.libraries_aql.execute", return_value=[1]):
            assert ops.get_library_by_id("libraries/1") is None

    def test_get_library_by_id_propagates_execute_errors(self) -> None:
        ops = LibrariesAqlOperations(MagicMock())
        with (
            patch("nomarr.persistence.database.libraries_aql.execute", side_effect=RuntimeError("db error")),
            pytest.raises(RuntimeError, match="db error"),
        ):
            ops.get_library_by_id("libraries/1")

    def test_get_library_by_key_returns_dict_or_none(self) -> None:
        ops = LibrariesAqlOperations(MagicMock())
        with patch("nomarr.persistence.database.libraries_aql.execute", return_value=[{"_key": "1"}]):
            assert ops.get_library_by_key("1") == {"_key": "1"}
        with patch("nomarr.persistence.database.libraries_aql.execute", return_value=[]):
            assert ops.get_library_by_key("1") is None

    def test_get_library_by_key_propagates_execute_errors(self) -> None:
        ops = LibrariesAqlOperations(MagicMock())
        with (
            patch("nomarr.persistence.database.libraries_aql.execute", side_effect=RuntimeError("db error")),
            pytest.raises(RuntimeError, match="db error"),
        ):
            ops.get_library_by_key("1")

    def test_get_library_by_name_returns_dict_or_none(self) -> None:
        ops = LibrariesAqlOperations(MagicMock())
        with patch("nomarr.persistence.database.libraries_aql.execute", return_value=[{"name": "Main"}]):
            assert ops.get_library_by_name("Main") == {"name": "Main"}
        with patch("nomarr.persistence.database.libraries_aql.execute", return_value=["bad"]):
            assert ops.get_library_by_name("Main") is None

    def test_list_libraries_filters_non_dict_rows(self) -> None:
        ops = LibrariesAqlOperations(MagicMock())
        with patch("nomarr.persistence.database.libraries_aql.execute", return_value=[{"_id": "libraries/1"}, 1]):
            assert ops.list_libraries(enabled_only=True) == [{"_id": "libraries/1"}]

    def test_list_library_keys_filters_non_string_rows(self) -> None:
        ops = LibrariesAqlOperations(MagicMock())
        with patch("nomarr.persistence.database.libraries_aql.execute", return_value=["main", 1]):
            assert ops.list_library_keys() == ["main"]

    def test_update_library_by_id_executes_update(self) -> None:
        ops = LibrariesAqlOperations(MagicMock())
        with patch("nomarr.persistence.database.libraries_aql.execute") as exec_mock:
            ops.update_library_by_id("libraries/main", {"watch_mode": "poll"})

        _, _, bind_vars = exec_mock.call_args.args
        assert bind_vars == {"library_key": "main", "fields": {"watch_mode": "poll"}}

    def test_update_library_by_id_rejects_non_id_values(self) -> None:
        ops = LibrariesAqlOperations(MagicMock())
        with pytest.raises(ValueError, match="full Arango _id"):
            ops.update_library_by_id("main", {"watch_mode": "poll"})
