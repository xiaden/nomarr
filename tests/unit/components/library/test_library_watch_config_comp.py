"""Tests for nomarr.components.library.library_watch_config_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_watch_config_comp import (
    get_library_watch_config,
    list_watchable_libraries,
)


class TestListWatchableLibraries:
    """Tests for list_watchable_libraries."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_projected_fields_only(self) -> None:
        mock_db = MagicMock()
        libraries = [
            {
                "_id": "libraries/one",
                "root_path": "C:/music/one",
                "watch_mode": "poll",
                "is_enabled": True,
                "name": "Main Library",
            },
            {
                "_id": "libraries/two",
                "root_path": "C:/music/two",
                "watch_mode": "event",
                "extra": "ignored",
            },
        ]

        with patch(
            "nomarr.components.library.library_watch_config_comp.list_watchable_library_records",
            return_value=libraries,
        ) as list_records:
            result = list_watchable_libraries(mock_db)

        assert result == [
            {
                "_id": "libraries/one",
                "root_path": "C:/music/one",
                "watch_mode": "poll",
            },
            {
                "_id": "libraries/two",
                "root_path": "C:/music/two",
                "watch_mode": "event",
            },
        ]
        list_records.assert_called_once_with(mock_db)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_watchable_query_for_filtering_behavior(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.library.library_watch_config_comp.list_watchable_library_records",
            return_value=[],
        ) as list_records:
            result = list_watchable_libraries(mock_db)

        assert result == []
        list_records.assert_called_once_with(mock_db)
        mock_db.libraries.list_libraries.assert_not_called()


class TestGetLibraryWatchConfig:
    """Tests for get_library_watch_config."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_library_is_missing(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.library.library_watch_config_comp.get_library_record",
            return_value=None,
        ) as get_record:
            result = get_library_watch_config(mock_db, "libraries/missing")

        assert result is None
        get_record.assert_called_once_with(mock_db, "libraries/missing", include_scan=False)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_projected_watch_config_fields_only(self) -> None:
        mock_db = MagicMock()
        library_doc = {
            "_id": "libraries/one",
            "root_path": "C:/music/one",
            "watch_mode": "poll",
            "is_enabled": False,
            "name": "Main Library",
            "scan_status": "idle",
        }

        with patch(
            "nomarr.components.library.library_watch_config_comp.get_library_record",
            return_value=library_doc,
        ) as get_record:
            result = get_library_watch_config(mock_db, "libraries/one")

        assert result == {
            "root_path": "C:/music/one",
            "watch_mode": "poll",
            "is_enabled": False,
        }
        get_record.assert_called_once_with(mock_db, "libraries/one", include_scan=False)
