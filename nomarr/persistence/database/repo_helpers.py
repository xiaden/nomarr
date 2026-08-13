"""Shared helpers for repository modules.

Contains utility functions used across multiple repository files to avoid
duplication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.helpers.dto.repo_dto import SongRow

if TYPE_CHECKING:
    from sqlalchemy.engine import Row


def _song_row_to_dto(row: Row) -> SongRow:
    """Convert a SQLAlchemy ``Row`` to a ``SongRow`` TypedDict."""
    m = row._mapping
    return SongRow(
        id=m["id"],
        library_id=m["library_id"],
        folder_id=m["folder_id"],
        path=m["path"],
        normalized_path=m["normalized_path"],
        file_size=m["file_size"],
        modified_time=m["modified_time"],
        duration_seconds=m["duration_seconds"],
        chromaprint=m["chromaprint"],
        needs_tagging=m["needs_tagging"],
        is_valid=m["is_valid"],
        tagged=m["tagged"],
        calibration_hash=m["calibration_hash"],
        write_claimed_by=m["write_claimed_by"],
        last_tagged_at=m["last_tagged_at"],
        scanned_at=m["scanned_at"],
        created_at=m["created_at"],
    )
