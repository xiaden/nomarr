"""Tests for nomarr.components.tagging.tag_cleanup_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.tagging.tag_cleanup_comp import (
    cleanup_orphaned_tags,
    get_orphaned_tag_count,
)


def _make_cleanup_db(
    *,
    orphan_ids: list[str],
    delete_result: int = 0,
) -> MagicMock:
    """Build a db mock for orphan cleanup tests."""
    mock_db = MagicMock()
    mock_db.library.maintenance.list_orphaned_tag_ids.return_value = orphan_ids
    mock_db.library.maintenance.delete_tags_by_ids.return_value = delete_result
    return mock_db


class TestCleanupOrphanedTags:
    """Tests for cleanup_orphaned_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_and_skips_delete_when_no_orphans(self) -> None:
        mock_db = _make_cleanup_db(orphan_ids=[])

        result = cleanup_orphaned_tags(mock_db)

        assert result == 0
        mock_db.library.maintenance.delete_tags_by_ids.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_orphans_and_returns_deleted_count(self) -> None:
        orphan_ids = ["tags/3", "tags/4"]
        mock_db = _make_cleanup_db(orphan_ids=orphan_ids, delete_result=2)

        result = cleanup_orphaned_tags(mock_db)

        assert result == 2
        mock_db.library.maintenance.delete_tags_by_ids.assert_called_once_with(orphan_ids)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_library_facade(self) -> None:
        mock_db = _make_cleanup_db(orphan_ids=["tags/1"], delete_result=1)

        cleanup_orphaned_tags(mock_db)

        mock_db.library.maintenance.list_orphaned_tag_ids.assert_called_once()


class TestGetOrphanedTagCount:
    """Tests for get_orphaned_tag_count."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_no_orphans(self) -> None:
        mock_db = _make_cleanup_db(orphan_ids=[])

        result = get_orphaned_tag_count(mock_db)

        assert result == 0

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_count_of_orphaned_tags(self) -> None:
        mock_db = _make_cleanup_db(orphan_ids=["tags/3", "tags/4"])

        result = get_orphaned_tag_count(mock_db)

        assert result == 2

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_library_facade(self) -> None:
        mock_db = _make_cleanup_db(orphan_ids=[])

        get_orphaned_tag_count(mock_db)

        mock_db.library.maintenance.list_orphaned_tag_ids.assert_called_once()
