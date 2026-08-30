"""Domain values used by library persistence intent facades."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from nomarr.helpers.constants.pipeline_states import (
    CAL_AXIS,
    ML_AXIS,
    PIPELINE_AXIS_FIELDS,
    PIPELINE_DEFAULTS,
    SCAN_AXIS,
    WRITE_AXIS,
)

WatchMode = Literal["off", "event", "poll"]
FileWriteMode = Literal["none", "minimal", "full"]


@dataclass(frozen=True, slots=True)
class LibraryUpdate:
    """Typed changes to a library's configuration."""

    name: str | None = None
    root_path: str | None = None
    is_enabled: bool | None = None
    watch_mode: WatchMode | None = None
    file_write_mode: FileWriteMode | None = None
    library_auto_write: bool | None = None
    updated_at: int | None = None

    def __post_init__(self) -> None:
        if self.watch_mode is not None and self.watch_mode not in {"off", "event", "poll"}:
            raise ValueError(f"Invalid watch_mode: {self.watch_mode}")
        if self.file_write_mode is not None and self.file_write_mode not in {"none", "minimal", "full"}:
            raise ValueError(f"Invalid file_write_mode: {self.file_write_mode}")


@dataclass(frozen=True, slots=True)
class LibraryPipelineState:
    """The four user-visible processing states for a library."""

    scan_state: str = PIPELINE_DEFAULTS["scan_state"]
    ml_state: str = PIPELINE_DEFAULTS["ml_state"]
    calibration_state: str = PIPELINE_DEFAULTS["calibration_state"]
    tag_write_state: str = PIPELINE_DEFAULTS["tag_write_state"]

    @classmethod
    def defaults(cls) -> LibraryPipelineState:
        return cls(**PIPELINE_DEFAULTS)

    @classmethod
    def from_mapping(cls, values: dict[str, str]) -> LibraryPipelineState:
        return cls(*(values.get(axis, PIPELINE_DEFAULTS[axis]) for axis in PIPELINE_AXIS_FIELDS))

    def __post_init__(self) -> None:
        valid_values = dict(zip(PIPELINE_AXIS_FIELDS, (SCAN_AXIS, ML_AXIS, CAL_AXIS, WRITE_AXIS), strict=True))
        for axis, values in valid_values.items():
            value = getattr(self, axis)
            if value not in values:
                raise ValueError(f"Invalid {axis}: {value}")

    def to_state_mapping(self) -> dict[str, str]:
        return {axis: getattr(self, axis) for axis in PIPELINE_AXIS_FIELDS}


@dataclass(frozen=True, slots=True)
class LibraryFolder:
    """Folder summary scoped to a domain library."""

    path: str
    name: str | None = None
    parent_path: str | None = None
    mtime: int | None = None
    file_count: int | None = None
    last_scanned_at: int | None = None

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("LibraryFolder.path must not be blank")


@dataclass(frozen=True, slots=True)
class LibraryScan:
    """Latest scan summary for a domain library."""

    scan_type: str
    status: str = "in_progress"
    started_at: int = 0
    heartbeat_at: int | None = None
    finished_at: int | None = None
    files_found: int = 0
    files_processed: int = 0
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.scan_type.strip():
            raise ValueError("LibraryScan.scan_type must not be blank")


__all__ = ["LibraryFolder", "LibraryPipelineState", "LibraryScan", "LibraryUpdate"]
