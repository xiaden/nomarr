"""Tests for the locator-free orphan maintenance workflow.

``prune_orphaned_files_workflow`` consumes only the count-only
``LibrarySongsDb.prune_orphaned_songs`` intent: persistence resolves the orphan
row handles privately, and the workflow sees and returns only an integer count.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.workflows.platform.prune_orphaned_files_wf import prune_orphaned_files_workflow


@pytest.mark.unit
def test_prune_returns_count_only() -> None:
    db = MagicMock()
    db.library.prune_orphaned_songs.return_value = 3

    result = prune_orphaned_files_workflow(db)

    assert result == {"files_pruned": 3}
    db.library.prune_orphaned_songs.assert_called_once_with()


@pytest.mark.unit
def test_prune_zero_returns_zero() -> None:
    db = MagicMock()
    db.library.prune_orphaned_songs.return_value = 0

    result = prune_orphaned_files_workflow(db)

    assert result == {"files_pruned": 0}
