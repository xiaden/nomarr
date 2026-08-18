"""Tests for library path reconciliation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.reconcile_paths_comp import reconcile_library_paths


@pytest.mark.unit
def test_delete_policy_validates_rows_shifted_by_deletions() -> None:
    """Rows shifted into a page by deletion must still be reconciled."""
    db = MagicMock()
    rows = [
        {"path": "/invalid/one", "library_id": 1},
        {"path": "/invalid/two", "library_id": 1},
        {"path": "/valid", "library_id": 1},
    ]
    offsets: list[int] = []

    def list_rows(_db: object, *, library_id: int, limit: int, offset: int) -> tuple[list[dict[str, object]], int]:
        del library_id, limit
        offsets.append(offset)
        return rows[offset : offset + 2], len(rows)

    def remove_song(path: str) -> None:
        rows[:] = [row for row in rows if row["path"] != path]

    db.library.remove_song_by_path.side_effect = remove_song

    def build_path(*, stored_path: str, **_kwargs: object) -> SimpleNamespace:
        if stored_path.startswith("/invalid"):
            return SimpleNamespace(status="not_found", reason="missing", is_valid=lambda: False)
        return SimpleNamespace(status="valid", reason=None, is_valid=lambda: True)

    with (
        patch(
            "nomarr.components.library.reconcile_paths_comp.get_library_stats",
            return_value={"total_files": 3},
        ),
        patch(
            "nomarr.components.library.reconcile_paths_comp.list_songs",
            side_effect=list_rows,
        ),
        patch(
            "nomarr.components.library.reconcile_paths_comp.build_library_path_from_db",
            side_effect=build_path,
        ),
    ):
        result = reconcile_library_paths(db, library_id=1, policy="delete_invalid", batch_size=2)

    assert result["total_files"] == 3
    assert result["not_found"] == 2
    assert result["deleted_files"] == 2
    assert result["valid_files"] == 1
    assert offsets == [0, 0, 1]
    assert rows == [{"path": "/valid", "library_id": 1}]
