"""Tests for nomarr.components.library.library_watch_config_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_watch_config_comp import (
    get_library_watch_config,
    list_watchable_libraries,
)
from nomarr.helpers.dto.library_dto import LibraryDict


class TestListWatchableLibraries:
    """Tests for list_watchable_libraries."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_projected_fields_only(self) -> None:
        mock_db = MagicMock()
        libraries = [
            LibraryDict(
                id=1,
                name="Main Library",
                root_path="C:/music/one",
                is_enabled=True,
                created_at=0,
                updated_at=0,
                watch_mode="poll",
            ),
            LibraryDict(
                id=2,
                name="Lib",
                root_path="C:/music/two",
                is_enabled=True,
                created_at=0,
                updated_at=0,
                watch_mode="event",
            ),
        ]

        with patch(
            "nomarr.components.library.library_watch_config_comp.list_watchable_library_records",
            return_value=libraries,
        ) as list_records:
            result = list_watchable_libraries(mock_db)

        assert result == [
            {
                "id": 1,
                "root_path": "C:/music/one",
                "watch_mode": "poll",
            },
            {
                "id": 2,
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
            result = get_library_watch_config(mock_db, 999)

        assert result is None
        get_record.assert_called_once_with(mock_db, 999, include_scan=False)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_projected_watch_config_fields_only(self) -> None:
        mock_db = MagicMock()
        library_doc = {
            "id": 1,
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
            result = get_library_watch_config(mock_db, 1)

        assert result == {
            "root_path": "C:/music/one",
            "watch_mode": "poll",
            "is_enabled": False,
        }
        get_record.assert_called_once_with(mock_db, 1, include_scan=False)
