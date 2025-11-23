"""
Path handling utilities for library-scoped operations.

Rules:
- Only import from standard library (dataclasses, pathlib, typing)
- No imports from nomarr.services, nomarr.workflows, nomarr.persistence, or nomarr.interfaces
- Keep pure: no I/O, no config loading, no side effects
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LibraryPath:
    """
    Represents a file path with library context.

    Provides clean separation between absolute paths (for operations),
    library association (for ownership), and relative paths (for display).

    All paths are normalized and resolved to canonical form during initialization.

    Attributes:
        absolute: Absolute filesystem path (canonical, normalized)
        library_id: ID of owning library
        library_root: Absolute path to library root

    Examples:
        >>> lp = LibraryPath(absolute="/music/rock/song.mp3", library_id=1, library_root="/music")
        >>> lp.relative
        'rock/song.mp3'
    """

    absolute: str
    library_id: int
    library_root: str

    @property
    def relative(self) -> str:
        """
        Get path relative to library root for display/UI purposes.

        Returns POSIX-style path string for consistent cross-platform representation.
        """
        abs_path = Path(self.absolute)
        root_path = Path(self.library_root)
        return abs_path.relative_to(root_path).as_posix()

    def __post_init__(self) -> None:
        """
        Normalize and validate paths during initialization.

        - Expands user home directory (~)
        - Resolves symlinks and relative path components
        - Ensures both paths are absolute
        - Validates that absolute path is within library_root
        - Updates frozen attributes with normalized values
        """
        # Normalize both paths (expand ~, resolve symlinks, make absolute)
        abs_path = Path(self.absolute).expanduser().resolve()
        root_path = Path(self.library_root).expanduser().resolve()

        # Ensure both are absolute paths
        if not abs_path.is_absolute():
            raise ValueError(f"Absolute path is not absolute after normalization: {self.absolute}")
        if not root_path.is_absolute():
            raise ValueError(f"Library root is not absolute after normalization: {self.library_root}")

        # Ensure file path is within library root
        try:
            abs_path.relative_to(root_path)
        except ValueError as e:
            raise ValueError(f"Path {abs_path} is not within library root {root_path}") from e

        # Update frozen dataclass attributes with normalized values
        object.__setattr__(self, "absolute", str(abs_path))
        object.__setattr__(self, "library_root", str(root_path))
