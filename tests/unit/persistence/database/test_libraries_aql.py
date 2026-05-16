"""Focused tests for canonical ``LibrariesAqlOperations`` helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.libraries_aql import LibrariesAqlOperations


@pytest.mark.unit
@pytest.mark.mocked
def test_remove_library_orphaned_tag_cleanup_only_queries_song_edges() -> None:
    db = MagicMock()
    db.collections.return_value = []
    ops = LibrariesAqlOperations(db)

    ops.remove_library("libraries/1")

    executed_queries = [call.args[0] for call in db.aql.execute.call_args_list]

    assert executed_queries
    assert all("tag_model_output" not in query for query in executed_queries)
    assert "song_has_tags" in executed_queries[-1]
