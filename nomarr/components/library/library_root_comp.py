"""Library root path validation and security boundary enforcement."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from nomarr.components.library.library_records_comp import list_library_records
from nomarr.helpers.files_helper import resolve_library_path

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_base_library_root(library_root_config: str | None) -> Path:
    """Resolve and validate the configured base library root.

    Raises ValueError if not configured, does not exist, or is not a directory.
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

    except (OSError, ValueError) as e:
        msg = f"Invalid base library root: {e}"
        raise ValueError(msg) from e


def normalize_library_root(base_library_root: Path, raw_root: str | Path) -> str:
    """Normalize and validate a user-provided library root path.

    Ensures the path exists, is a directory, and is within the security boundary.
    Raises ValueError if invalid or outside the base root.
    """
    # Convert raw_root to string for processing
    raw_root_str = str(raw_root)
    raw_path = Path(raw_root_str)

    if raw_path.is_absolute():
        try:
            abs_path = raw_path.resolve()
            user_path = os.path.relpath(abs_path, base_library_root)
        except (ValueError, OSError) as e:
            msg = f"Cannot compute relative path from base root: {e}"
            raise ValueError(msg) from e
    else:
        user_path = raw_root_str

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


def ensure_no_overlapping_library_root(db: Database, candidate_root: str, *, ignore_id: str | None = None) -> None:
    """Ensure a candidate library root does not overlap with any existing library.

    Raises ValueError if roots overlap — library roots must be disjoint.
    """
    # Resolve candidate to canonical absolute path
    candidate_path = Path(candidate_root).resolve()

    existing_libraries = list_library_records(db, enabled_only=False, include_scan=False)

    for library in existing_libraries:
        if ignore_id is not None and library.id == ignore_id:
            continue

        existing_path = Path(library.root_path).resolve()

        try:
            candidate_path.relative_to(existing_path)
            msg = (
                f"Library root '{candidate_root}' is nested inside "
                f"existing library '{library.name}' at '{library.root_path}'. "
                f"Library roots must be disjoint."
            )
            raise ValueError(msg)
        except ValueError as e:
            if "is nested inside" in str(e):
                raise
            # Paths are not related — continue

        try:
            existing_path.relative_to(candidate_path)
            msg = (
                f"Existing library '{library.name}' at '{library.root_path}' "
                f"is nested inside new library root '{candidate_root}'. "
                f"Library roots must be disjoint."
            )
            raise ValueError(msg)
        except ValueError as e:
            if "is nested inside" in str(e):
                raise


def resolve_path_within_library(
    library_root: str,
    user_path: str | Path,
    *,
    must_exist: bool = True,
    must_be_file: bool | None = None,
) -> Path:
    """Resolve and validate a path within a library root.

    Wraps resolve_library_path. For library roots, use normalize_library_root instead.
    """
    return resolve_library_path(
        library_root=library_root,
        user_path=user_path,
        must_exist=must_exist,
        must_be_file=must_be_file,
    )


def validate_library_root(library_root: Path) -> None:
    """Validate that a library root directory is accessible and non-empty.

    Raises OSError if the root doesn't exist, is inaccessible, or is empty.
    """
    if not library_root.exists():
        msg = f"Library root does not exist: {library_root} \u2014 the volume may not be mounted"
        raise OSError(msg)
    if not library_root.is_dir():
        msg = f"Library root is not a directory: {library_root}"
        raise OSError(msg)

    try:
        entries = list(library_root.iterdir())
    except PermissionError:
        msg = f"Library root is not accessible (permission denied): {library_root}"
        raise OSError(msg) from None
    except OSError as e:
        msg = f"Library root is not accessible (mount/IO error): {library_root} \u2014 {e}"
        raise OSError(msg) from e

    if not entries:
        msg = f"Library root is empty: {library_root} \u2014 the volume may not be mounted correctly"
        raise OSError(msg)
