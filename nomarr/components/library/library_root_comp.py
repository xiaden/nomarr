"""Library root path validation and security boundary enforcement.

This component handles all path security, normalization, and validation
for library root paths. It enforces the security boundary (base library_root)
and ensures library roots do not overlap.

Architecture:
- Components may import helpers + persistence
- This component primarily uses helpers (Path, resolve_library_path)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nomarr.helpers.files_helper import resolve_library_path

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_base_library_root(library_root_config: str | None) -> Path:
    """Get the configured base library_root (security boundary).

    This is the top-level directory that all library roots must be nested under.
    It defines the security boundary for file access.

    Args:
        library_root_config: Raw library_root value from config

    Returns:
        Absolute Path to library_root directory

    Raises:
        ValueError: If library_root not configured or invalid

    """
    if not library_root_config:
        msg = "Library root not configured"
        raise ValueError(msg)

    try:
        base = Path(library_root_config).expanduser().resolve()

        if not base.exists():
            msg = f"Base library root does not exist: {library_root_config}"
            raise ValueError(msg)
        if not base.is_dir():
            msg = f"Base library root is not a directory: {library_root_config}"
            raise ValueError(msg)

        return base

    except Exception as e:
        msg = f"Invalid base library root: {e}"
        raise ValueError(msg) from e


def normalize_library_root(base_library_root: Path, raw_root: str | Path) -> str:
    """Normalize and validate a user-provided library root path.

    This ensures the library root:
    - Exists and is a directory
    - Is strictly within the configured base library_path
    - Is canonicalized to an absolute path

    Args:
        base_library_root: Base library root from config (security boundary)
        raw_root: User-provided library root (absolute or relative)

    Returns:
        Canonical absolute path string for storage in database

    Raises:
        ValueError: If path is invalid or outside base library root

    """
    import os

    # Convert raw_root to string for processing
    raw_root_str = str(raw_root)

    # Determine if input is absolute or relative
    raw_path = Path(raw_root_str)

    if raw_path.is_absolute():
        # Convert absolute path to relative path from base root
        try:
            # Resolve to handle any symlinks/.. in the path
            abs_path = raw_path.resolve()
            # Get relative path from base root
            user_path = os.path.relpath(abs_path, base_library_root)
        except (ValueError, OSError) as e:
            # relpath can fail if paths are on different drives on Windows
            msg = f"Cannot compute relative path from base root: {e}"
            raise ValueError(msg) from e
    else:
        # Already relative, use as-is
        user_path = raw_root_str

    # Validate using resolve_library_path
    try:
        resolved = resolve_library_path(
            library_root=base_library_root,
            user_path=user_path,
            must_exist=True,
            must_be_file=False,
        )
    except ValueError as e:
        # Re-raise with more context
        msg = f"Library root validation failed: {e}"
        raise ValueError(msg) from e

    return str(resolved)


def ensure_no_overlapping_library_root(
    db: Database,
    candidate_root: str,
    *,
    ignore_id: str | None = None,
) -> None:
    """Ensure a candidate library root does not overlap with existing libraries.

    This enforces the business rule that all library roots must be disjoint -
    no library may be nested inside another, and no two libraries may share
    overlapping directory trees.

    Args:
        db: Database instance for querying existing libraries
        candidate_root: Absolute path to validate
        ignore_id: Optional library ID to ignore (for updates)

    Raises:
        ValueError: If candidate_root overlaps with any existing library root

    """
    # Resolve candidate to canonical absolute path
    candidate_path = Path(candidate_root).resolve()

    # Fetch all existing libraries
    existing_libraries = db.libraries.list_libraries(enabled_only=False)

    for library in existing_libraries:
        # Skip if this is the library being updated
        if ignore_id is not None and library["_id"] == ignore_id:
            continue

        # Resolve existing library root
        existing_path = Path(library["root_path"]).resolve()

        # Check if candidate is inside existing library
        try:
            candidate_path.relative_to(existing_path)
            # If no ValueError raised, candidate is inside existing
            msg = (
                f"Library root '{candidate_root}' is nested inside "
                f"existing library '{library['name']}' at '{library['root_path']}'. "
                f"Library roots must be disjoint."
            )
            raise ValueError(
                msg,
            )
        except ValueError as e:
            # relative_to raises ValueError if not a subpath - this is expected for disjoint paths
            if "is nested inside" in str(e):
                # Re-raise our custom error
                raise
            # Otherwise, paths are not related - continue checking

        # Check if existing library is inside candidate
        try:
            existing_path.relative_to(candidate_path)
            # If no ValueError raised, existing is inside candidate
            msg = (
                f"Existing library '{library['name']}' at '{library['root_path']}' "
                f"is nested inside new library root '{candidate_root}'. "
                f"Library roots must be disjoint."
            )
            raise ValueError(
                msg,
            )
        except ValueError as e:
            # relative_to raises ValueError if not a subpath - this is expected for disjoint paths
            if "is nested inside" in str(e):
                # Re-raise our custom error
                raise
            # Otherwise, paths are not related - continue checking


def resolve_path_within_library(
    library_root: str,
    user_path: str | Path,
    *,
    must_exist: bool = True,
    must_be_file: bool | None = None,
) -> Path:
    """Resolve a user-provided path within a library root.

    This is a wrapper around helpers.files.resolve_library_path
    for validating paths within a library (e.g., scanning subdirectories, loading specific files).

    DO NOT use this for validating library roots themselves - use normalize_library_root
    for that, since library roots need validation against the base library root.

    Args:
        library_root: Absolute path to library root directory
        user_path: User-provided path (relative or absolute) to resolve
        must_exist: If True, require path to exist (default: True)
        must_be_file: If True, require file; if False, require directory; if None, allow either

    Returns:
        Resolved absolute Path within library root

    Raises:
        ValueError: If path validation fails

    """
    return resolve_library_path(
        library_root=library_root,
        user_path=user_path,
        must_exist=must_exist,
        must_be_file=must_be_file,
    )
