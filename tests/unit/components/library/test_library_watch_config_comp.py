"""Tests for nomarr.components.library.library_watch_config_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

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
        mock_db.libraries.list_watchable_libraries.return_value = [
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
        mock_db.libraries.list_watchable_libraries.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_watchable_query_for_filtering_behavior(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.list_watchable_libraries.return_value = []

        result = list_watchable_libraries(mock_db)

        assert result == []
        mock_db.libraries.list_watchable_libraries.assert_called_once_with()
        mock_db.libraries.list_libraries.assert_not_called()


class TestGetLibraryWatchConfig:
    """Tests for get_library_watch_config."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_library_is_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.get_library.return_value = None

        result = get_library_watch_config(mock_db, "libraries/missing")

        assert result is None
        mock_db.libraries.get_library.assert_called_once_with("libraries/missing")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_projected_watch_config_fields_only(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.get_library.return_value = {
            "_id": "libraries/one",
            "root_path": "C:/music/one",
            "watch_mode": "poll",
            "is_enabled": False,
            "name": "Main Library",
            "scan_status": "idle",
        }

        result = get_library_watch_config(mock_db, "libraries/one")

        assert result == {
            "root_path": "C:/music/one",
            "watch_mode": "poll",
            "is_enabled": False,
        }
        mock_db.libraries.get_library.assert_called_once_with("libraries/one")
