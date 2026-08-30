"""Tests for nomarr.components.tagging.tag_cleanup_comp module.

Phase 6 rewrite: asserts the migrated domain-facing API. The component
delegates the whole orphan discovery + deletion to the sealed facade intent
``db.library.cleanup_orphaned_tags() -> TagCleanupResult(deleted, orphaned)``;
there is no count-only orphan method, so ``get_orphaned_tag_count`` is removed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags
from nomarr.helpers.dataclasses.song_tag_dataclass import TagCleanupResult


class TestCleanupOrphanedTags:
    """Tests for cleanup_orphaned_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_result_when_no_orphans(self) -> None:
        mock_db = MagicMock()
        mock_db.library.cleanup_orphaned_tags.return_value = TagCleanupResult(deleted=0, orphaned=0)

        result = cleanup_orphaned_tags(mock_db)

        assert result == TagCleanupResult(deleted=0, orphaned=0)
        mock_db.library.cleanup_orphaned_tags.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_typed_result_with_deleted_and_orphaned_counts(self) -> None:
        mock_db = MagicMock()
        mock_db.library.cleanup_orphaned_tags.return_value = TagCleanupResult(deleted=2, orphaned=3)

        result = cleanup_orphaned_tags(mock_db)

        assert result.deleted == 2
        assert result.orphaned == 3

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_library_facade(self) -> None:
        mock_db = MagicMock()
        mock_db.library.cleanup_orphaned_tags.return_value = TagCleanupResult(deleted=0, orphaned=0)

        cleanup_orphaned_tags(mock_db)

        mock_db.library.cleanup_orphaned_tags.assert_called_once()
