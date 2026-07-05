from pathlib import Path

from nomarr.components.library.library_records_comp import find_library_containing_path, get_library_record
from nomarr.helpers.dto.path_dto import LibraryPath
from nomarr.helpers.files_helper import is_audio_file
from nomarr.persistence.db import Database


def build_library_path_from_input(raw_path: str, db: Database) -> LibraryPath:
    """Build LibraryPath from user input, validating against current library config."""
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

    library = find_library_containing_path(db, str(absolute))
    if not library:
        return LibraryPath(
            relative="",
            absolute=absolute,
            library_id=None,
            status="invalid_config",
            reason="Path is outside all configured library roots",
        )

    library_root = Path(library["root_path"]).resolve()
    try:
        relative_path = absolute.relative_to(library_root)
        relative_str = str(relative_path).replace("\\", "/")
    except ValueError:
        return LibraryPath(
            relative="",
            absolute=absolute,
            library_id=library["_id"],
            status="invalid_config",
            reason=f"Path not relative to library root: {library_root}",
        )

    if not absolute.exists():
        return LibraryPath(
            relative=relative_str,
            absolute=absolute,
            library_id=library["_id"],
            status="not_found",
            reason="File does not exist on disk",
        )

    if not absolute.is_file():
        return LibraryPath(
            relative=relative_str,
            absolute=absolute,
            library_id=library["_id"],
            status="invalid_config",
            reason="Path is a directory, not a file",
        )

    if not is_audio_file(str(absolute)):
        return LibraryPath(
            relative=relative_str,
            absolute=absolute,
            library_id=library["_id"],
            status="invalid_config",
            reason="Not a supported audio file format",
        )

    return LibraryPath(relative=relative_str, absolute=absolute, library_id=library["_id"], status="valid", reason=None)


def build_library_path_from_db(
    stored_path: str,
    db: Database,
    library_id: str | None = None,
    check_disk: bool = True,
) -> LibraryPath:
    """Build LibraryPath from a database-stored path, re-validating against current config."""
    if library_id:
        library = get_library_record(db, library_id, include_scan=False)
        if not library or not library["is_enabled"]:
            return LibraryPath(
                relative=stored_path,
                absolute=Path(stored_path),
                library_id=library_id,
                status="invalid_config",
                reason=f"Library {library_id} is disabled or no longer exists",
            )

        library_root = Path(library["root_path"]).resolve()

        if Path(stored_path).is_absolute():
            absolute = Path(stored_path).resolve()
        else:
            absolute = (library_root / stored_path).resolve()

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

        library = find_library_containing_path(db, str(absolute))
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

    return LibraryPath(
        relative=relative_str,
        absolute=absolute,
        library_id=library_id,
        status="valid" if check_disk else "unknown",
        reason=None,
    )


def get_library_root(library_path: LibraryPath, db: Database) -> Path | None:
    """Get the library root path for a given LibraryPath."""
    if not library_path.library_id:
        return None

    library = get_library_record(db, library_path.library_id, include_scan=False)
    if not library:
        return None

    return Path(library["root_path"]).resolve()
