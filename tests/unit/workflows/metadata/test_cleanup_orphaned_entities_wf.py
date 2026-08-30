"""Unit tests for ``cleanup_orphaned_entities_wf`` — dry_run branching.

Asserts the truthful dry_run safety semantic: ``dry_run=True`` counts orphaned
tags via the non-destructive ``count_orphaned_tags`` intent and performs NO
deletion; ``dry_run=False`` calls the destructive ``cleanup_orphaned_tags``
intent and reports its real ``TagCleanupResult``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.song_tag_dataclass import TagCleanupResult
from nomarr.workflows.metadata.cleanup_orphaned_entities_wf import cleanup_orphaned_entities_workflow

pytestmark = [pytest.mark.unit, pytest.mark.mocked]

PATCH_BASE = "nomarr.workflows.metadata.cleanup_orphaned_entities_wf"


class TestCleanupOrphanedEntitiesWorkflow:
    """Tests for ``cleanup_orphaned_entities_workflow``."""

    @patch(f"{PATCH_BASE}.count_orphaned_tags")
    @patch(f"{PATCH_BASE}.cleanup_orphaned_tags")
    def test_dry_run_counts_but_does_not_delete(self, mock_cleanup, mock_count) -> None:
        """dry_run=True counts via count_orphaned_tags and performs NO deletion."""
        mock_count.return_value = 5
        mock_db = MagicMock()

        result = cleanup_orphaned_entities_workflow(mock_db, dry_run=True)

        assert result == {
            "orphaned_counts": {"tags": 5},
            "deleted_counts": {"tags": 0},
            "total_orphaned": 5,
            "total_deleted": 0,
        }
        mock_count.assert_called_once_with(mock_db)
        mock_cleanup.assert_not_called()

    @patch(f"{PATCH_BASE}.count_orphaned_tags")
    @patch(f"{PATCH_BASE}.cleanup_orphaned_tags")
    def test_live_run_deletes_and_reports_real_counts(self, mock_cleanup, mock_count) -> None:
        """dry_run=False deletes via cleanup and reports the real TagCleanupResult."""
        mock_cleanup.return_value = TagCleanupResult(deleted=3, orphaned=7)
        mock_db = MagicMock()

        result = cleanup_orphaned_entities_workflow(mock_db, dry_run=False)

        assert result == {
            "orphaned_counts": {"tags": 7},
            "deleted_counts": {"tags": 3},
            "total_orphaned": 7,
            "total_deleted": 3,
        }
        mock_cleanup.assert_called_once_with(mock_db)
        mock_count.assert_not_called()
