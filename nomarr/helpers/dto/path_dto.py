"""Path validation DTOs for secure filesystem operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PathStatus = Literal["valid", "invalid_config", "not_found", "unknown"]


@dataclass(frozen=True)
class LibraryPath:
    """
    Canonical representation of a library file path with validation status.

    This DTO encodes:
    - relative: Normalized path relative to library root
    - absolute: Resolved absolute path
    - library_id: Which library configuration this path belongs to (if known)
    - status: Current validation state under the active configuration
    - reason: Optional diagnostic message for non-valid states

    Status meanings:
    - "valid": Path is within configured library root, exists, and is accessible
    - "invalid_config": Path is outside current library boundaries or config changed
    - "not_found": Path structure is valid but file doesn't exist on disk
    - "unknown": Haven't checked disk yet, but config mapping looks okay

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
    library_id: str | None  # Which library this belongs to (ArangoDB _id or None)
    status: PathStatus  # Validation status under current config
    reason: str | None = None  # Diagnostic message for non-valid status

    def is_valid(self) -> bool:
        """Check if this path is valid for filesystem operations."""
        return self.status == "valid"

    def __str__(self) -> str:
        """String representation uses absolute path."""
        return str(self.absolute)
