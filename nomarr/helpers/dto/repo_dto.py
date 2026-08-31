"""TypedDict DTOs for repository return types.

These mirror the SQLAlchemy model columns from Part A and provide
type-safe return types for all Part C repository methods. Import
only from ``typing`` and ``datetime``.
"""

from __future__ import annotations

from typing import TypedDict


class LibraryRow(TypedDict):
    """Single row from the ``libraries`` table."""

    id: int
    name: str
    path: str
    library_type: str
    auto_tag: int  # Integer, default 0
    auto_curate: int  # Integer, default 0
    watch_mode: str
    file_write_mode: str
    created_at: int  # BigInteger
    updated_at: int  # BigInteger


class SongRow(TypedDict):
    """Single row from the ``songs`` table."""

    id: int
    library_id: int
    folder_id: int | None
    path: str
    normalized_path: str
    file_size: int
    modified_time: int
    duration_seconds: float | None
    chromaprint: str | None
    needs_tagging: bool
    is_valid: bool
    tagged: bool
    calibration_hash: str | None
    write_claimed_by: str | None
    last_tagged_at: int | None
    scanned_at: int | None
    created_at: int


class NumericSongTagMatchRow(SongRow):
    """A song matched by numeric tag-distance, with its match metadata.

    Transitional persistence-row DTO: carries the complete ``SongRow`` fields
    plus the matched tag's string ``value`` (``matched_tag``) and the absolute
    numeric ``distance`` from the requested target. This is a persistence-rows
    projection for the SQL-paginated numeric search; it is not a domain-model
    or feature-contract ledger addition (ADR-032/ADR-041 keep storage shapes
    inside the persistence layer).
    """

    matched_tag: str
    distance: float


class LibraryFolderRow(TypedDict):
    """Single row from the ``library_folders`` table."""

    id: int
    library_id: int
    parent_id: int | None
    path: str
    name: str | None
    mtime: int | None
    file_count: int | None
    last_scanned_at: int | None


class LibraryScanRow(TypedDict):
    """Single row from the ``library_scans`` table."""

    id: int
    library_id: int
    scan_type: str
    status: str
    started_at: int
    heartbeat_at: int | None
    finished_at: int | None
    files_found: int
    files_processed: int
    error: str | None


class TagRow(TypedDict):
    """Single row from the ``tags`` table.

    ``confidence`` and ``tier`` are legacy columns: kept for schema
    stability, never populated by any code path. ML scores live on
    ``tag_model_output`` (see DD-song-domain-repair Q5).
    """

    id: int
    name: str
    value: str
    namespace: str
    parent_tag_id: int | None
    source: str
    confidence: float | None
    tier: int | None
    created_at: int


class SongTagRow(TypedDict):
    """Single row from the ``song_tags`` junction table."""

    id: int
    song_id: int
    tag_id: int
    confidence: float
    source: str
    created_at: int


class PipelineStateRow(TypedDict):
    """Single row from the ``pipeline_states`` table."""

    id: int
    library_id: int
    state_key: str
    state_data: dict
    updated_at: int


class MetaRow(TypedDict):
    """Single row from the ``meta`` KV table."""

    key: str
    value: dict


class LockRow(TypedDict):
    """Internal repository row for lock persistence."""

    key: str
    value: dict


class HealthRow(TypedDict):
    """Single row from the ``worker_health`` table."""

    id: int
    worker_id: str
    status: str
    last_seen: int


class SessionRow(TypedDict):
    """Single row from the ``sessions`` table."""

    id: str
    data: dict
    expires_at: int


class SongStateRow(TypedDict):
    """Single row from the ``song_states`` lookup table."""

    id: int
    name: str
    description: str | None


class SongStateAssignmentRow(TypedDict):
    """Single row from the ``song_state_assignments`` junction table."""

    id: int
    song_id: int
    state_id: int
    created_at: int


__all__ = [
    "HealthRow",
    "LibraryFolderRow",
    "LibraryRow",
    "LibraryScanRow",
    "LockRow",
    "MetaRow",
    "NumericSongTagMatchRow",
    "PipelineStateRow",
    "SessionRow",
    "SongRow",
    "SongStateAssignmentRow",
    "SongStateRow",
    "SongTagRow",
    "TagRow",
]
