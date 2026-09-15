from pathlib import Path
from typing import Literal

from nomarr.components.library.library_records_comp import find_library_containing_path, get_library_by_name
from nomarr.helpers.dto.path_dto import LibraryPath, PathStatus
from nomarr.helpers.exceptions import FilesystemError
from nomarr.helpers.files_helper import is_audio_file
from nomarr.helpers.fs_contract import FsFact, canonicalize, fact_from_error
from nomarr.persistence.db import Database

_ConfigStatus = Literal["valid", "invalid_config"]


def _derive_status(
    *,
    config_status: _ConfigStatus,
    config_reason: str | None,
    fs_fact: FsFact | None,
) -> tuple[PathStatus, str | None]:
    """Single producer of the derived ``status``/``reason`` view (D-B1, SEAM-3).

    ``invalid_config`` is reserved for config/semantic conditions provable without
    touching the filesystem; any filesystem fact downgrades an otherwise-valid
    config mapping to ``"unknown"``. ``"not_found"`` is never produced (D-B2).
    """
    if config_status != "valid":
        return "invalid_config", config_reason
    if fs_fact is not None:
        return "unknown", fs_fact.detail
    return "valid", None


def _build_path(
    *,
    relative: str,
    absolute: Path,
    library_id: str | None,
    config_status: _ConfigStatus = "valid",
    config_reason: str | None = None,
    fs_fact: FsFact | None = None,
) -> LibraryPath:
    """Construct a ``LibraryPath`` through the single derivation helper."""
    status, reason = _derive_status(
        config_status=config_status,
        config_reason=config_reason,
        fs_fact=fs_fact,
    )
    return LibraryPath(
        relative=relative,
        absolute=absolute,
        library_id=library_id,
        status=status,
        reason=reason,
        fs_fact=fs_fact,
    )


def build_library_path_from_input(raw_path: str, db: Database) -> LibraryPath:
    """Build LibraryPath from user input (API, CLI, etc.).

    This is the primary entry point for external path inputs. Resolution is
    config/semantic-only: it validates the path against the current library
    configuration and classifies any filesystem failure into ``fs_fact`` rather
    than probing for existence.
    - "valid": Path is within a library root and no filesystem fact applies
    - "invalid_config": Path is outside all configured library roots, is not an
      audio path, or is no longer relative to its root
    - "unknown": Config mapping looks okay but a filesystem fact was observed

    Args:
        raw_path: Raw file path from user input (absolute or relative)
        db: Database instance to look up library configuration

    Returns:
        LibraryPath with derived status and structured filesystem fact

    """
    # Canonicalise the input path; a filesystem failure is a typed fact, not a leak.
    try:
        absolute = canonicalize(raw_path, strict=False)
    except OSError as exc:
        return _build_path(
            relative="",
            absolute=Path(raw_path),
            library_id=None,
            fs_fact=fact_from_error(exc, path=raw_path),
        )

    # Find which library contains this path
    try:
        library = find_library_containing_path(db, str(absolute))
    except FilesystemError as exc:
        return _build_path(relative="", absolute=absolute, library_id=None, fs_fact=exc.fact)

    if not library:
        return _build_path(
            relative="",
            absolute=absolute,
            library_id=None,
            config_status="invalid_config",
            config_reason="Path is outside all configured library roots",
        )

    # Calculate relative path
    try:
        library_root = canonicalize(library.root_path, strict=False)
    except OSError as exc:
        return _build_path(
            relative="",
            absolute=absolute,
            library_id=library.name,
            fs_fact=fact_from_error(exc, path=library.root_path),
        )

    try:
        relative_path = absolute.relative_to(library_root)
        relative_str = str(relative_path).replace("\\", "/")  # Normalize to forward slashes
    except ValueError:
        return _build_path(
            relative="",
            absolute=absolute,
            library_id=library.name,
            config_status="invalid_config",
            config_reason=f"Path not relative to library root: {library_root}",
        )

    # Supported audio format is a config/semantic property (extension-only).
    if not is_audio_file(str(absolute)):
        return _build_path(
            relative=relative_str,
            absolute=absolute,
            library_id=library.name,
            config_status="invalid_config",
            config_reason="Not a supported audio file format",
        )

    return _build_path(relative=relative_str, absolute=absolute, library_id=library.name)


def build_library_path_from_db(
    stored_path: str,
    db: Database,
    library_id: str | None = None,
) -> LibraryPath:
    """Build LibraryPath from database-stored path.

    This is used when reading paths from queue tables, the file collection, etc.
    The stored path may be absolute or relative depending on storage format.

    This function re-validates stored paths against the CURRENT configuration,
    detecting cases where config has changed (library root moved/changed).
    Resolution is config/semantic-only: it never probes for file existence, so a
    config-resolvable path is ``valid`` regardless of any filesystem condition,
    which is instead carried in ``fs_fact``.

    Args:
        stored_path: Path as stored in database (may be relative or absolute)
        db: Database instance to look up current library configuration
        library_id: Optional natural library ``name`` if known from DB join

    Returns:
        LibraryPath with status reflecting current config validity

    """
    # If we have a library name, fetch that library's configuration
    if library_id:
        library = get_library_by_name(db, library_id)
        if not library or not library.is_enabled:
            # Library was disabled or deleted
            return _build_path(
                relative=stored_path,
                absolute=Path(stored_path),
                library_id=library_id,
                config_status="invalid_config",
                config_reason=f"Library {library_id} is disabled or no longer exists",
            )

        try:
            library_root = canonicalize(library.root_path, strict=False)
        except OSError as exc:
            return _build_path(
                relative=stored_path,
                absolute=Path(stored_path),
                library_id=library_id,
                fs_fact=fact_from_error(exc, path=library.root_path),
            )

        # stored_path might be relative or absolute
        absolute_raw = stored_path if Path(stored_path).is_absolute() else str(library_root / stored_path)
        try:
            absolute = canonicalize(absolute_raw, strict=False)
        except OSError as exc:
            return _build_path(
                relative=stored_path,
                absolute=Path(absolute_raw),
                library_id=library_id,
                fs_fact=fact_from_error(exc, path=absolute_raw),
            )

        # Verify it's still within the library root
        try:
            relative_path = absolute.relative_to(library_root)
            relative_str = str(relative_path).replace("\\", "/")
        except ValueError:
            return _build_path(
                relative=stored_path,
                absolute=absolute,
                library_id=library_id,
                config_status="invalid_config",
                config_reason=f"Path no longer within library root: {library_root}",
            )

    else:
        # No library_id provided, need to find which library contains this path
        try:
            absolute = canonicalize(stored_path, strict=False)
        except OSError as exc:
            return _build_path(
                relative=stored_path,
                absolute=Path(stored_path),
                library_id=None,
                fs_fact=fact_from_error(exc, path=stored_path),
            )

        try:
            found = find_library_containing_path(db, str(absolute))
        except FilesystemError as exc:
            return _build_path(relative=stored_path, absolute=absolute, library_id=None, fs_fact=exc.fact)

        if not found:
            return _build_path(
                relative=stored_path,
                absolute=absolute,
                library_id=None,
                config_status="invalid_config",
                config_reason="Stored path is outside all configured library roots",
            )

        try:
            library_root = canonicalize(found.root_path, strict=False)
        except OSError as exc:
            return _build_path(
                relative=stored_path,
                absolute=absolute,
                library_id=found.name,
                fs_fact=fact_from_error(exc, path=found.root_path),
            )

        try:
            relative_path = absolute.relative_to(library_root)
            relative_str = str(relative_path).replace("\\", "/")
        except ValueError:
            return _build_path(
                relative=stored_path,
                absolute=absolute,
                library_id=found.name,
                config_status="invalid_config",
                config_reason=f"Stored path not relative to library root: {library_root}",
            )

        library_id = found.name

    return _build_path(relative=relative_str, absolute=absolute, library_id=library_id)


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

    library = get_library_by_name(db, library_path.library_id)
    if not library:
        return None

    return Path(library.root_path).resolve()
