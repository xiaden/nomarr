"""Unit tests for ``cleanup_orphaned_tags_wf`` — branching logic around dry_run."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.song_tag_dataclass import TagCleanupResult
from nomarr.workflows.library.cleanup_orphaned_tags_wf import cleanup_orphaned_tags_workflow

pytestmark = [pytest.mark.unit, pytest.mark.mocked]

PATCH_BASE = "nomarr.workflows.library.cleanup_orphaned_tags_wf"


class TestCleanupOrphanedTagsWorkflow:
    """Tests for ``cleanup_orphaned_tags_workflow``."""

    @patch(f"{PATCH_BASE}.count_orphaned_tags")
    @patch(f"{PATCH_BASE}.cleanup_orphaned_tags")
    def test_dry_run_counts_but_does_not_delete(self, mock_cleanup, mock_count) -> None:
        """dry_run=True counts via count_orphaned_tags and performs NO deletion."""
        mock_count.return_value = 5
        mock_db = MagicMock()

        result = cleanup_orphaned_tags_workflow(mock_db, dry_run=True)

        assert result == {"orphaned_count": 5, "deleted_count": 0}
        mock_count.assert_called_once_with(mock_db)
        mock_cleanup.assert_not_called()

    @patch(f"{PATCH_BASE}.count_orphaned_tags")
    @patch(f"{PATCH_BASE}.cleanup_orphaned_tags")
    def test_live_run_counts_and_deletes(self, mock_cleanup, mock_count) -> None:
        """dry_run=False reports the discovered orphan count and the deletion count."""
        mock_cleanup.return_value = TagCleanupResult(deleted=3, orphaned=3)
        mock_db = MagicMock()

        result = cleanup_orphaned_tags_workflow(mock_db, dry_run=False)

        assert result == {"orphaned_count": 3, "deleted_count": 3}
        mock_cleanup.assert_called_once_with(mock_db)
        mock_count.assert_not_called()

    @patch(f"{PATCH_BASE}.cleanup_orphaned_tags")
    def test_zero_orphaned_tags_still_calls_cleanup_and_returns_zero(self, mock_cleanup) -> None:
        """When no orphaned tags exist, cleanup is still called and deleted_count is 0."""
        mock_cleanup.return_value = TagCleanupResult(deleted=0, orphaned=0)
        mock_db = MagicMock()

        result = cleanup_orphaned_tags_workflow(mock_db, dry_run=False)

        assert result == {"orphaned_count": 0, "deleted_count": 0}
        mock_cleanup.assert_called_once_with(mock_db)  # cleanup always called when not dry_run
