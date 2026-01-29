"""File tags I/O workflows - read and remove tags from audio files."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_input
from nomarr.components.tagging.tagging_reader_comp import read_tags_from_file
from nomarr.components.tagging.tagging_remove_comp import remove_tags_from_file

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def read_file_tags_workflow(db: Database, path: str, namespace: str) -> dict[str, Any]:
    """Read tags from an audio file.

    Args:
        db: Database instance
        path: Absolute file path (must be under library_root)
        namespace: Tag namespace to filter by

    Returns:
        Dictionary of tag_key -> value(s)

    Raises:
        ValueError: If path is outside library_root or invalid
        RuntimeError: If file cannot be read

    """
    # Build and validate LibraryPath
    library_path = build_library_path_from_input(raw_path=path, db=db)

    if not library_path.is_valid():
        msg = f"Invalid path: {library_path.reason}"
        raise ValueError(msg)

    # Read tags using component
    tags = read_tags_from_file(library_path, namespace)

    # Convert to dict for API response
    return tags.to_dict()


def remove_file_tags_workflow(db: Database, path: str, namespace: str) -> int:
    """Remove all namespaced tags from an audio file.

    Args:
        db: Database instance
        path: Absolute file path (must be under library_root)
        namespace: Tag namespace to remove

    Returns:
        Number of tags removed

    Raises:
        ValueError: If path is outside library_root or invalid
        RuntimeError: If file cannot be modified

    """
    # Build and validate LibraryPath
    library_path = build_library_path_from_input(raw_path=path, db=db)

    if not library_path.is_valid():
        msg = f"Invalid path: {library_path.reason}"
        raise ValueError(msg)

    # Remove tags using component
    return remove_tags_from_file(library_path, namespace)

