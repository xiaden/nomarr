from pathlib import Path

from nomarr.helpers.dto.path_dto import LibraryPath
from nomarr.helpers.files_helper import is_audio_file
from nomarr.persistence.db import Database


def build_library_path_from_input(raw_path: str, db: Database) -> LibraryPath:
    """Build LibraryPath from user input (API, CLI, etc.).

    This is the primary entry point for external path inputs.
    It validates the path against current library configuration and sets status:
    - "valid": Path is within a library root, exists, and is accessible
    - "invalid_config": Path is outside all configured library roots
    - "not_found": Path is within a library root but file doesn't exist

    Args:
        raw_path: Raw file path from user input (absolute or relative)
        db: Database instance to look up library configuration

    Returns:
        LibraryPath with status and diagnostic info

    Example:
        path = build_library_path_from_input("/music/song.mp3", db)
        if path.is_valid():
            # Safe to perform filesystem operations
            process_file(path)
        else:
            # Handle error based on status
            log.error(f"Invalid path: {path.reason}")

    """
    # Resolve to absolute path
    try:
        absolute = Path(raw_path).resolve()
    except (ValueError, OSError) as e:
        return LibraryPath(
            relative="",
            absolute=Path(raw_path),
            library_id=None,
            status="invalid_config",
            reason=f"Cannot resolve path: {e}",
        )

    # Find which library contains this path
    library = db.libraries.find_library_containing_path(str(absolute))
    if not library:
        return LibraryPath(
            relative="",
            absolute=absolute,
            library_id=None,
            status="invalid_config",
            reason="Path is outside all configured library roots",
        )

    # Calculate relative path
    library_root = Path(library["root_path"]).resolve()
    try:
        relative_path = absolute.relative_to(library_root)
        relative_str = str(relative_path).replace("\\", "/")  # Normalize to forward slashes
    except ValueError:
        return LibraryPath(
            relative="",
            absolute=absolute,
            library_id=library["_id"],
            status="invalid_config",
            reason=f"Path not relative to library root: {library_root}",
        )

    # Check if file exists
    if not absolute.exists():
        return LibraryPath(
            relative=relative_str,
            absolute=absolute,
            library_id=library["_id"],
            status="not_found",
            reason="File does not exist on disk",
        )

    # Check if it's a file (not directory)
    if not absolute.is_file():
        return LibraryPath(
            relative=relative_str,
            absolute=absolute,
            library_id=library["_id"],
            status="invalid_config",
            reason="Path is a directory, not a file",
        )

    # Check if it's a supported audio file
    if not is_audio_file(str(absolute)):
        return LibraryPath(
            relative=relative_str,
            absolute=absolute,
            library_id=library["_id"],
            status="invalid_config",
            reason="Not a supported audio file format",
        )

    # All checks passed
    return LibraryPath(relative=relative_str, absolute=absolute, library_id=library["_id"], status="valid", reason=None)


def build_library_path_from_db(
    stored_path: str, db: Database, library_id: str | None = None, check_disk: bool = True,
) -> LibraryPath:
    """Build LibraryPath from database-stored path.

    This is used when reading paths from queue tables, library_files, etc.
    The stored path may be absolute or relative depending on storage format.

    This function re-validates stored paths against the CURRENT configuration,
    detecting cases where config has changed (library root moved/changed).

    Args:
        stored_path: Path as stored in database (may be relative or absolute)
        db: Database instance to look up current library configuration
        library_id: Optional library ID if known from DB join
        check_disk: Whether to check if file exists (default: True)

    Returns:
        LibraryPath with status reflecting current config validity

    Example:
        # When processing a file from discovery
        file_record = db.files.get_file(file_id)
        path = build_library_path_from_db(file_record["path"], db)
        if not path.is_valid():
            # Config changed, path no longer valid
            db.files.mark_invalid(file_id, path.reason)
            return

    """
    # If we have a library_id, fetch that library's configuration
    if library_id:
        library = db.libraries.get_library(library_id)
        if not library or not library["is_enabled"]:
            # Library was disabled or deleted
            return LibraryPath(
                relative=stored_path,
                absolute=Path(stored_path),
                library_id=library_id,
                status="invalid_config",
                reason=f"Library {library_id} is disabled or no longer exists",
            )

        library_root = Path(library["root_path"]).resolve()

        # Try to construct absolute path
        # stored_path might be relative or absolute
        if Path(stored_path).is_absolute():
            absolute = Path(stored_path).resolve()
        else:
            absolute = (library_root / stored_path).resolve()

        # Verify it's still within the library root
        try:
            relative_path = absolute.relative_to(library_root)
            relative_str = str(relative_path).replace("\\", "/")
        except ValueError:
            return LibraryPath(
                relative=stored_path,
                absolute=absolute,
                library_id=library_id,
                status="invalid_config",
                reason=f"Path no longer within library root: {library_root}",
            )

    else:
        # No library_id provided, need to find which library contains this path
        try:
            absolute = Path(stored_path).resolve()
        except (ValueError, OSError) as e:
            return LibraryPath(
                relative=stored_path,
                absolute=Path(stored_path),
                library_id=None,
                status="invalid_config",
                reason=f"Cannot resolve stored path: {e}",
            )

        library = db.libraries.find_library_containing_path(str(absolute))
        if not library:
            return LibraryPath(
                relative=stored_path,
                absolute=absolute,
                library_id=None,
                status="invalid_config",
                reason="Stored path is outside all configured library roots",
            )

        library_root = Path(library["root_path"]).resolve()
        try:
            relative_path = absolute.relative_to(library_root)
            relative_str = str(relative_path).replace("\\", "/")
        except ValueError:
            return LibraryPath(
                relative=stored_path,
                absolute=absolute,
                library_id=library["_id"],
                status="invalid_config",
                reason=f"Stored path not relative to library root: {library_root}",
            )

        library_id = library["_id"]

    # Optionally check disk
    if check_disk:
        if not absolute.exists():
            return LibraryPath(
                relative=relative_str,
                absolute=absolute,
                library_id=library_id,
                status="not_found",
                reason="File no longer exists on disk",
            )

        if not absolute.is_file():
            return LibraryPath(
                relative=relative_str,
                absolute=absolute,
                library_id=library_id,
                status="invalid_config",
                reason="Stored path is now a directory, not a file",
            )

        if not is_audio_file(str(absolute)):
            return LibraryPath(
                relative=relative_str,
                absolute=absolute,
                library_id=library_id,
                status="invalid_config",
                reason="Stored path is no longer a supported audio file",
            )

    # Valid (or unknown if we didn't check disk)
    return LibraryPath(
        relative=relative_str,
        absolute=absolute,
        library_id=library_id,
        status="valid" if check_disk else "unknown",
        reason=None,
    )


def get_library_root(library_path: LibraryPath, db: Database) -> Path | None:
    """Get the library root path for a given LibraryPath.

    Args:
        library_path: A validated LibraryPath
        db: Database instance

    Returns:
        Path to library root, or None if library_id is unknown or library not found

    """
    if not library_path.library_id:
        return None

    library = db.libraries.get_library(library_path.library_id)
    if not library:
        return None

    return Path(library["root_path"]).resolve()
