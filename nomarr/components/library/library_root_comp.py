"""Library root path validation and security boundary enforcement."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from nomarr.components.library.library_records_comp import list_all_libraries
from nomarr.helpers.exceptions import FilesystemError
from nomarr.helpers.files_helper import resolve_library_path
from nomarr.helpers.fs_contract import FsFact, canonicalize, fact_from_error, probe_fact

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database


def get_base_library_root(library_root_config: str | None) -> Path:
    """Resolve and validate the configured base library root.

    Raises ``ValueError`` if not configured, or ``FilesystemError`` carrying a
    classified fact when the filesystem cannot confirm the root. A transient or
    storage error is never relabelled as a permanent config error.
    """
    if not library_root_config:
        msg = "Library root not configured"
        raise ValueError(msg)

    try:
        base = canonicalize(Path(library_root_config).expanduser(), strict=False)
    except OSError as exc:
        msg = "Invalid base library root"
        raise FilesystemError(msg, fact=fact_from_error(exc, path=library_root_config)) from exc

    fact = probe_fact(base)
    if fact.presence != "present":
        msg = "Invalid base library root"
        raise FilesystemError(msg, fact=fact) from None

    try:
        mode = os.stat(base).st_mode
    except OSError as exc:
        msg = "Invalid base library root"
        raise FilesystemError(msg, fact=fact_from_error(exc, path=str(base))) from exc

    if not stat.S_ISDIR(mode):
        msg = "Invalid base library root"
        raise FilesystemError(
            msg,
            fact=FsFact(
                presence="unknown",
                kind="wrong_resource_type",
                errno=errno.ENOTDIR,
                detail=f"{base}: not a directory",
            ),
        ) from None

    return base


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
            abs_path = canonicalize(raw_path, strict=False)
            user_path = os.path.relpath(abs_path, base_library_root)
        except OSError as e:
            msg = "Cannot compute relative path from base root"
            raise FilesystemError(msg, fact=fact_from_error(e, path=raw_root_str)) from e
        except ValueError as e:
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
    except FilesystemError:
        # Preserve the structured fact; do not re-wrap the typed error.
        raise
    except ValueError as e:
        # Re-raise with more context
        msg = f"Library root validation failed: {e}"
        raise ValueError(msg) from e

    return str(resolved)


def ensure_no_overlapping_library_root(
    db: Database,
    candidate_root: str,
    *,
    ignore: Library | None = None,
) -> None:
    """Ensure a candidate library root does not overlap with any existing library.

    ``ignore`` is the domain ``Library`` being modified (matched by natural
    ``name``); it is skipped so the caller can move/validate its own root.

    Raises ValueError if roots overlap — library roots must be disjoint.
    """
    # Resolve candidate to canonical absolute path
    candidate_path = canonicalize(candidate_root, strict=False)

    existing_libraries = list_all_libraries(db)

    for library in existing_libraries:
        if ignore is not None and library.name == ignore.name:
            continue

        existing_path = canonicalize(library.root_path, strict=False)

        # Containment is structural; the decision never matches a message substring.
        if candidate_path.is_relative_to(existing_path):
            msg = (
                f"Library root '{candidate_root}' overlaps existing library "
                f"'{library.name}' at '{library.root_path}'. Library roots must be disjoint."
            )
            raise ValueError(msg)

        if existing_path.is_relative_to(candidate_path):
            msg = (
                f"Existing library '{library.name}' at '{library.root_path}' overlaps "
                f"new library root '{candidate_root}'. Library roots must be disjoint."
            )
            raise ValueError(msg)


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
    fact = probe_fact(library_root)
    if fact.presence != "present":
        msg = "Library root is not accessible"
        raise OSError(fact.errno, msg)

    try:
        mode = os.stat(library_root).st_mode
    except OSError as exc:
        msg = "Library root is not accessible"
        raise OSError(exc.errno, msg) from exc

    if not stat.S_ISDIR(mode):
        msg = "Library root is not a directory"
        raise OSError(errno.ENOTDIR, msg)

    try:
        entries = list(library_root.iterdir())
    except PermissionError as e:
        msg = "Library root is not accessible"
        raise OSError(e.errno or errno.EACCES, msg) from e
    except OSError as e:
        msg = "Library root is not accessible"
        raise OSError(e.errno, msg) from e

    if not entries:
        msg = "Library root is empty"
        raise OSError(msg)
