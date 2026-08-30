"""Domain value objects and the typed update command for the library surface.

These types deliberately contain no database identifiers, table metadata, or
storage vocabulary. The persistence facade maps them to storage-owned rows
internally per ADR-032/ADR-041. ``Library`` itself lives in
``library_dataclass.py``; this sibling module holds the typed intent command
(``LibraryUpdate``) and the immutable library pipeline / folder / scan value
objects. No type here exposes a generated PostgreSQL id or a row payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from nomarr.helpers.constants.pipeline_states import (
    CAL_AXIS,
    ML_AXIS,
    PIPELINE_DEFAULTS,
    SCAN_AXIS,
    WRITE_AXIS,
)

WatchMode = Literal["off", "event", "poll"]
FileWriteMode = Literal["none", "minimal", "full"]

__all__ = [
    "FileWriteMode",
    "LibraryFolder",
    "LibraryPipelineState",
    "LibraryScan",
    "LibraryUpdate",
    "WatchMode",
]


@dataclass(frozen=True, slots=True)
class LibraryUpdate:
    """Immutable, typed update command for a library's configuration fields.

    Replaces the arbitrary column dictionaries the facade previously accepted.
    Every field is optional; ``None`` means "leave unchanged". Only domain
    fields are present — there is no generated id and no storage vocabulary.
    """

    name: str | None = None
    root_path: str | None = None
    is_enabled: bool | None = None
    watch_mode: WatchMode | None = None
    file_write_mode: FileWriteMode | None = None
    library_auto_write: bool | None = None
    updated_at: int | None = None

    def __post_init__(self) -> None:
        if self.watch_mode is not None and self.watch_mode not in ("off", "event", "poll"):
            raise ValueError(f"Invalid watch_mode: {self.watch_mode!r}")
        if self.file_write_mode is not None and self.file_write_mode not in ("none", "minimal", "full"):
            raise ValueError(f"Invalid file_write_mode: {self.file_write_mode!r}")
        if self.is_enabled is not None and not isinstance(self.is_enabled, bool):
            raise TypeError("LibraryUpdate.is_enabled must be a bool")
        if self.library_auto_write is not None and not isinstance(self.library_auto_write, bool):
            raise TypeError("LibraryUpdate.library_auto_write must be a bool")
        if self.updated_at is not None and not isinstance(self.updated_at, int):
            raise TypeError("LibraryUpdate.updated_at must be an int")


@dataclass(frozen=True, slots=True)
class LibraryPipelineState:
    """Immutable value object for the canonical four library pipeline axes.

    Backed by ``pipeline_states`` rows inside persistence; this object hides
    those rows and their ``state_data`` payloads. Defaults come from
    ``PIPELINE_DEFAULTS`` for a freshly created library.
    """

    scan_state: str = PIPELINE_DEFAULTS["scan_state"]
    ml_state: str = PIPELINE_DEFAULTS["ml_state"]
    calibration_state: str = PIPELINE_DEFAULTS["calibration_state"]
    tag_write_state: str = PIPELINE_DEFAULTS["tag_write_state"]

    @classmethod
    def defaults(cls) -> LibraryPipelineState:
        """Return the pipeline state for a freshly created library."""
        return cls(
            scan_state=PIPELINE_DEFAULTS["scan_state"],
            ml_state=PIPELINE_DEFAULTS["ml_state"],
            calibration_state=PIPELINE_DEFAULTS["calibration_state"],
            tag_write_state=PIPELINE_DEFAULTS["tag_write_state"],
        )

    @classmethod
    def from_mapping(cls, mapping: dict[str, str]) -> LibraryPipelineState:
        """Build a pipeline state from an axis-field → pole-value mapping."""
        return cls(
            scan_state=mapping.get("scan_state", PIPELINE_DEFAULTS["scan_state"]),
            ml_state=mapping.get("ml_state", PIPELINE_DEFAULTS["ml_state"]),
            calibration_state=mapping.get("calibration_state", PIPELINE_DEFAULTS["calibration_state"]),
            tag_write_state=mapping.get("tag_write_state", PIPELINE_DEFAULTS["tag_write_state"]),
        )

    def to_state_mapping(self) -> dict[str, str]:
        """Project to the axis-field → pole-value mapping used internally.

        Persistence uses this to round-trip rows; callers never see row
        payloads. Keys are exactly ``PIPELINE_AXIS_FIELDS``.
        """
        return {
            "scan_state": self.scan_state,
            "ml_state": self.ml_state,
            "calibration_state": self.calibration_state,
            "tag_write_state": self.tag_write_state,
        }

    def __post_init__(self) -> None:
        if self.scan_state not in SCAN_AXIS:
            raise ValueError(f"Invalid scan_state: {self.scan_state!r}")
        if self.ml_state not in ML_AXIS:
            raise ValueError(f"Invalid ml_state: {self.ml_state!r}")
        if self.calibration_state not in CAL_AXIS:
            raise ValueError(f"Invalid calibration_state: {self.calibration_state!r}")
        if self.tag_write_state not in WRITE_AXIS:
            raise ValueError(f"Invalid tag_write_state: {self.tag_write_state!r}")


@dataclass(frozen=True, slots=True)
class LibraryFolder:
    """Immutable folder value object, scoped to its library.

    Natural identity is the folder ``path`` relative to the library root. There
    is deliberately no folder id or parent id; the storage ``parent_id`` is
    expressed as the domain ``parent_path`` or left unknown.
    """

    path: str
    name: str | None = None
    parent_path: str | None = None
    mtime: int | None = None
    file_count: int | None = None
    last_scanned_at: int | None = None

    def __post_init__(self) -> None:
        if not self.path or not self.path.strip():
            raise ValueError("LibraryFolder.path must not be blank")


@dataclass(frozen=True, slots=True)
class LibraryScan:
    """Immutable scan summary for a library's scan lifecycle.

    There is deliberately no scan-row id. ``files_processed`` /
    ``files_found`` mirror the persisted counters; ``started_at`` and
    ``heartbeat_at`` are epoch-milliseconds per Nomarr timestamp conventions.
    """

    scan_type: str
    status: str = "in_progress"
    started_at: int = 0
    heartbeat_at: int | None = None
    files_processed: int = 0
    files_found: int = 0
    error: str | None = None
    finished_at: int | None = None

    def __post_init__(self) -> None:
        if not self.scan_type or not self.scan_type.strip():
            raise ValueError("LibraryScan.scan_type must not be blank")
