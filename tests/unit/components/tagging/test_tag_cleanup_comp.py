"""Tests for nomarr.components.tagging.tag_cleanup_comp module.

Asserts the migrated domain-facing API. ``count_orphaned_tags`` is the
non-destructive count-only read intent backing ``dry_run=True`` previews;
``cleanup_orphaned_tags`` delegates the whole orphan discovery + deletion to
the sealed facade intent ``db.library.admin_cleanup_orphaned_tags() ->
TagCleanupResult(deleted, orphaned)``. No integer tag-id bookkeeping remains.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags, count_orphaned_tags
from nomarr.helpers.dataclasses.song_tag_dataclass import TagCleanupResult


class TestCountOrphanedTags:
    """Tests for count_orphaned_tags (non-destructive dry_run read intent)."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_scalar_count(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_orphaned_tags.return_value = 3

        result = count_orphaned_tags(mock_db)

        assert result == 3
        mock_db.library.count_orphaned_tags.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_zero_when_no_orphans(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_orphaned_tags.return_value = 0

        result = count_orphaned_tags(mock_db)

        assert result == 0

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_never_deletes(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_orphaned_tags.return_value = 2

        count_orphaned_tags(mock_db)

        mock_db.library.admin_cleanup_orphaned_tags.assert_not_called()


class TestCleanupOrphanedTags:
    """Tests for cleanup_orphaned_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_result_when_no_orphans(self) -> None:
        mock_db = MagicMock()
        mock_db.library.admin_cleanup_orphaned_tags.return_value = TagCleanupResult(deleted=0, orphaned=0)

        result = cleanup_orphaned_tags(mock_db)

        assert result == TagCleanupResult(deleted=0, orphaned=0)
        mock_db.library.admin_cleanup_orphaned_tags.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_typed_result_with_deleted_and_orphaned_counts(self) -> None:
        mock_db = MagicMock()
        mock_db.library.admin_cleanup_orphaned_tags.return_value = TagCleanupResult(deleted=2, orphaned=3)

        result = cleanup_orphaned_tags(mock_db)

        assert result.deleted == 2
        assert result.orphaned == 3

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_library_facade(self) -> None:
        mock_db = MagicMock()
        mock_db.library.admin_cleanup_orphaned_tags.return_value = TagCleanupResult(deleted=0, orphaned=0)

        cleanup_orphaned_tags(mock_db)

        mock_db.library.admin_cleanup_orphaned_tags.assert_called_once()
