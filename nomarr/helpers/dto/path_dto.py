"""Path validation DTOs for secure filesystem operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

    from nomarr.helpers.fs_contract import FsFact

PathStatus = Literal["valid", "invalid_config", "not_found", "unknown"]


@dataclass(frozen=True)
class LibraryPath:
    """Canonical representation of a library file path with validation status.

    This DTO encodes:
    - relative: Normalized path relative to library root
    - absolute: Resolved absolute path
    - library_id: Natural name of the library configuration this path belongs to (if known)
    - status: Derived validation view under the active configuration
    - reason: Optional diagnostic message for non-valid states
    - fs_fact: The structured filesystem fact when resolution observed a filesystem
      failure, else ``None``

    **Single-producer derivation (D-B1, SEAM-3).** ``status``/``reason`` are a
    legacy config/semantic projection produced *only* by the factories in
    ``nomarr.components.infrastructure.path_comp``. ``fs_fact`` is the structured
    fact; never branch on ``reason``.

    Status meanings:
    - "valid": Path is within the configured library root and no filesystem fact applies
    - "invalid_config": Path is outside current library boundaries or config changed
      (a config/semantic judgment, provable without touching the filesystem)
    - "not_found": Retained for wire compatibility only; resolution no longer
      produces this status (D-B2)
    - "unknown": Config mapping looks okay but a filesystem fact was observed

    **IMPORTANT**: Do NOT construct LibraryPath directly. Use factory functions:
        from nomarr.components.infrastructure.path_comp import build_library_path_from_input, build_library_path_from_db

    These factories enforce validation and set status appropriately.
    Direct construction bypasses validation and should only be used in tests.

    Architectural contract:
    - Filesystem operations MUST check status == "valid" before proceeding
    - Persistence writes MUST receive LibraryPath (not construct from strings)
    - Workers MUST validate dequeued paths before processing
    """

    relative: str  # Path relative to library root (normalized, forward slashes)
    absolute: Path  # Absolute path (current container/system resolution)
    library_id: str | None  # Natural library name this path belongs to (or None)
    status: PathStatus  # Derived validation status under current config
    reason: str | None = None  # Diagnostic message for non-valid status
    fs_fact: FsFact | None = None  # Structured filesystem fact (server-side)

    def is_valid(self) -> bool:
        """Check if this path is valid for filesystem operations."""
        return self.status == "valid"

    def __str__(self) -> str:
        """String representation uses absolute path."""
        return str(self.absolute)
