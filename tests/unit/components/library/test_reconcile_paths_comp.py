"""Tests for library path reconciliation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.reconcile_paths_comp import reconcile_library_paths
from nomarr.components.library.song_query_types import HydratedSong
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_dataclass import Song


def _hydrated(path: str) -> HydratedSong:
    """Build the semantic ``HydratedSong`` a paged library read returns."""
    return HydratedSong(
        song=Song(
            path=path,
            normalized_path=path.lstrip("/"),
            file_size=0,
            modified_time=0,
            duration_seconds=None,
            chromaprint=None,
            needs_tagging=False,
            is_valid=True,
            tagged=False,
            calibration_hash=None,
            write_claimed_by=None,
            last_tagged_at=None,
            scanned_at=None,
            created_at=0,
        ),
        metadata={},
    )


@pytest.mark.unit
def test_delete_policy_validates_rows_shifted_by_deletions() -> None:
    """Rows shifted into a page by deletion must still be reconciled."""
    db = MagicMock()
    library = Library(name="Test Library", root_path="/music")
    rows = [
        _hydrated("/invalid/one"),
        _hydrated("/invalid/two"),
        _hydrated("/valid"),
    ]
    offsets: list[int] = []

    def list_rows(_db: object, *, library: Library, limit: int, offset: int) -> tuple[list[HydratedSong], int]:
        del library, limit
        offsets.append(offset)
        return rows[offset : offset + 2], len(rows)

    def remove_song(path: str, _library: Library) -> None:
        rows[:] = [row for row in rows if row.song.path != path]

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
        result = reconcile_library_paths(db, library=library, policy="delete_invalid", batch_size=2)

    assert result["total_files"] == 3
    assert result["not_found"] == 2
    assert result["deleted_files"] == 2
    assert result["valid_files"] == 1
    assert offsets == [0, 0, 1]
    assert [row.song.path for row in rows] == ["/valid"]
