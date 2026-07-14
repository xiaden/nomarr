"""Library dataclass used across Nomarr.

This module defines:
- WatchMode: Enum for library file-watching modes
- FileWriteMode: Enum for file tag-write modes
- Library: Canonical library configuration and state data container

Usage:
    from v2.nomarr.helpers.dataclasses.library_dataclass import Library
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields as dc_fields
from enum import StrEnum
from typing import Any


class WatchMode(StrEnum):
    """File-system watch strategy for a library."""

    OFF = "off"
    EVENT = "event"
    POLL = "poll"


class FileWriteMode(StrEnum):
    """Tag writeback level for audio files."""

    NONE = "none"
    MINIMAL = "minimal"
    FULL = "full"


# Pipeline axis state constants.
_SCAN_STATE_DEFAULT = "not_scanned"
_ML_STATE_DEFAULT = "not_ML_processed"
_CALIBRATION_STATE_DEFAULT = "not_calibrated"
_TAG_WRITE_STATE_DEFAULT = "not_written"


@dataclass(frozen=True, slots=True, kw_only=True)
class Library:
    """Canonical library configuration and state data container.

    Represents a single music library — a watched directory with its
    scanning, ML-processing, calibration, and tag-write pipeline state.

    The dataclass is frozen and slots-based.  Use ``copy_with(...)`` for
    targeted state transitions.
    """

    # ── Identity ──────────────────────────────────────────────────────
    id: str
    """Unique record identifier (e.g. ``"libraries/12345"``)."""

    name: str
    """Human-readable library name."""

    root_path: str
    """Absolute path to the root directory being watched."""

    # ── Configuration ─────────────────────────────────────────────────
    is_enabled: bool = True
    """Whether the library is active (scanned, processed)."""

    watch_mode: WatchMode = WatchMode.OFF
    """How filesystem changes are detected."""

    file_write_mode: FileWriteMode = FileWriteMode.FULL
    """Which tags are written back to audio files."""

    library_auto_write: bool = False
    """Automatically write tags after processing (vs manual)."""

    vector_search_thoroughness: int | None = None
    """Percentage of neighbourhoods to probe (1-100).  ``None`` = app default."""

    vector_group_size: int | None = None
    """Number of tracks per FAISS group.  ``None`` = app default."""

    # ── Scan state ────────────────────────────────────────────────────
    scan_status: str | None = None
    """Current scan status: ``"idle"``, ``"scanning"``, ``"complete"``, ``"error"``."""

    scan_progress: int | None = None
    """Files processed during current scan."""

    scan_total: int | None = None
    """Total files discovered during current scan."""

    scanned_at: int | None = None
    """Epoch milliseconds of last scan completion."""

    scan_error: str | None = None
    """Error message when ``scan_status == "error"``."""

    last_scan_started_at: int | None = None
    """Epoch milliseconds when the most recent scan began."""

    last_scan_at: int | None = None
    """Epoch milliseconds of the most recent scan completion."""

    scan_type_in_progress: str | None = None
    """``"quick"`` or ``"full"`` while a scan is running."""

    # ── Pipeline axis states ──────────────────────────────────────────
    scan_state: str = _SCAN_STATE_DEFAULT
    """File-discovery pipeline axis."""

    ml_state: str = _ML_STATE_DEFAULT
    """ML-processing pipeline axis."""

    calibration_state: str = _CALIBRATION_STATE_DEFAULT
    """Calibration pipeline axis."""

    tag_write_state: str = _TAG_WRITE_STATE_DEFAULT
    """Tag-writeback pipeline axis."""

    # ── Timestamps ────────────────────────────────────────────────────
    created_at: str | None = None
    """ISO-8601 creation timestamp, if tracked."""

    updated_at: str | None = None
    """ISO-8601 last-update timestamp, if tracked."""

    # ── Computed statistics (populated by service layer) ──────────────
    file_count: int = 0
    """Number of files linked to this library (not stored on the DB doc)."""

    folder_count: int = 0
    """Number of folders linked to this library (not stored on the DB doc)."""

    def __post_init__(self) -> None:
        """Validate required fields on construction."""
        if not self.id:
            raise ValueError("Library.id must not be empty")
        if not self.name:
            raise ValueError("Library.name must not be empty")
        if not self.name.strip():
            raise ValueError("Library.name must not be blank")
        if not self.root_path:
            raise ValueError("Library.root_path must not be empty")

    # ── Convenience ───────────────────────────────────────────────────

    @property
    def key(self) -> str:
        """Extract the record key from a qualified ``id``."""
        return self.id.rsplit("/", 1)[-1]

    @property
    def is_scanning(self) -> bool:
        """``True`` while a scan is in progress."""
        return self.scan_status == "scanning"

    # ── Factory ───────────────────────────────────────────────────────

    @classmethod
    def from_db_doc(cls, doc: dict[str, Any]) -> Library:
        """Construct a ``Library`` from a raw data-store document.

        Args:
            doc: Raw document dict from the data store.

        Returns:
            A fully populated ``Library`` instance.
        """
        return cls(
            id=doc["_id"],
            name=doc["name"],
            root_path=doc["root_path"],
            is_enabled=bool(doc.get("is_enabled", True)),
            watch_mode=WatchMode(doc.get("watch_mode", "off")),
            file_write_mode=FileWriteMode(doc.get("file_write_mode", "full")),
            library_auto_write=bool(doc.get("library_auto_write", False)),
            vector_search_thoroughness=doc.get("vector_search_thoroughness"),
            vector_group_size=doc.get("vector_group_size"),
            scan_status=doc.get("scan_status"),
            scan_progress=doc.get("scan_progress"),
            scan_total=doc.get("scan_total"),
            scanned_at=doc.get("scanned_at"),
            scan_error=doc.get("scan_error"),
            last_scan_started_at=doc.get("last_scan_started_at"),
            last_scan_at=doc.get("last_scan_at"),
            scan_type_in_progress=doc.get("scan_type_in_progress"),
            scan_state=doc.get("scan_state", _SCAN_STATE_DEFAULT),
            ml_state=doc.get("ml_state", _ML_STATE_DEFAULT),
            calibration_state=doc.get("calibration_state", _CALIBRATION_STATE_DEFAULT),
            tag_write_state=doc.get("tag_write_state", _TAG_WRITE_STATE_DEFAULT),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
            file_count=doc.get("file_count", 0),
            folder_count=doc.get("folder_count", 0),
        )

    # ── Targeted copy ─────────────────────────────────────────────────

    def copy_with(self, **overrides: Any) -> Library:
        """Return a new ``Library`` with the given fields replaced.

        Args:
            **overrides: Keyword arguments matching ``Library`` field names.

        Returns:
            A new frozen ``Library`` instance.
        """
        current: dict[str, Any] = {f.name: getattr(self, f.name) for f in dc_fields(self)}
        current.update(overrides)
        return Library(**current)
