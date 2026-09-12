"""File and folder scan operations for library scans.

Extracted from scan_lifecycle_comp — owns file-batch upsert, folder
cache management, deleted-file cleanup, and state bootstrap.

Overlap: concurrent song-domain repair (TASK-song-intent-facade-correction-A)
also edits this file. This change is scoped to the library-domain migration
(P4-S4) — moving folder cache upsert/stale-cleanup and file batch operations to
``Library`` natural scope and ``LibraryFolder`` values — and preserves the
concurrent song-domain hunks.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_song_query_comp import (
    list_songs,
)
from nomarr.components.library.library_song_state_comp import (
    library_has_tagged_files,
    transition_song_state,
)
from nomarr.helpers.constants.file_states import STATE_NOT_PROCESSED, STATE_PROCESSED
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryFolder
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongRemoval,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.helpers.exceptions import DatabaseStateError
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.components.library.song_query_types import HydratedSong
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Folder cache
# ---------------------------------------------------------------------------


def _folder_value(
    folder_path: str,
    mtime: int,
    file_count: int,
) -> LibraryFolder:
    """Build the folder-cache value persisted for quick scans."""
    return LibraryFolder(
        path=folder_path,
        mtime=mtime,
        file_count=file_count,
        last_scanned_at=now_ms().value,
    )


# ---------------------------------------------------------------------------
# Batch upsert
# ---------------------------------------------------------------------------


def _library_identity(library: Library) -> LibraryIdentity:
    if library.library_uuid is None:
        raise ValueError(f"Library {library.name!r} has no library_uuid")
    return LibraryIdentity(library_uuid=library.library_uuid, name=library.name, root_path=library.root_path)


def _upsert_batch(db: Database, library: Library, file_docs: list[dict[str, Any]]) -> list[SongIdentity]:
    """Batch-upsert scanned files through one typed atomic batch intent.

    Builds one :class:`SongUpsertInput` command per input document and calls
    ``db.library.add_songs_to_library_batch(commands)`` exactly once. State
    initialization for genuinely new rows is create-only and owned by
    persistence; this component neither reads nor repairs song state. Returns a
    :class:`SongIdentity` list in the same order as ``file_docs``.

    """
    if not file_docs:
        return []
    identity = _library_identity(library)
    commands = [
        SongUpsertInput(
            library=identity,
            path=str(doc["path"]),
            scan=SongScanUpdate(
                normalized_path=str(doc.get("normalized_path", doc["path"])),
                file_size=int(doc.get("file_size", 0)),
                modified_time=int(doc.get("modified_time", 0)),
                duration_seconds=doc.get("duration_seconds"),
                is_valid=bool(doc.get("is_valid", True)),
            ),
            last_tagged_at=doc.get("last_tagged_at"),
        )
        for doc in file_docs
    ]
    return db.library.add_songs_to_library_batch(commands)


# ---------------------------------------------------------------------------
# File snapshots
# ---------------------------------------------------------------------------


def snapshot_existing_files(
    db: Database,
    library: Library,
) -> tuple[dict[str, HydratedSong], bool]:
    """Load the pre-scan snapshot of existing library files.

    Args:
        db: Persistence facade.
        library: Natural library scope to snapshot.

    Returns:
        A ``(existing_files, has_tagged_files)`` tuple. ``existing_files`` maps
        each existing file's physical ``path`` to its ``HydratedSong`` carrier
        (semantic ``Song`` plus derived metadata), not a row or raw document.
        ``has_tagged_files`` reports whether the library already has tagged
        files.

    """
    files_tuple = list_songs(db, library=library, limit=1_000_000, offset=0)
    existing_files_dict: dict[str, HydratedSong] = {f.song.path: f for f in files_tuple[0]}
    has_tagged_files = library_has_tagged_files(db, library)
    return existing_files_dict, has_tagged_files


# ---------------------------------------------------------------------------
# Batch file operations
# ---------------------------------------------------------------------------


def upsert_scanned_files(
    db: Database,
    library: Library,
    file_entries: list[dict[str, Any]],
    edge_bootstraps: list[dict[str, Any]] | None = None,
) -> list[SongIdentity]:
    """Batch-upsert scanned files and optionally bootstrap state edges.

    Args:
        db: Persistence facade.
        library: Natural library scope being scanned.
        file_entries: Scan entry documents, one per discovered file, keyed by
            ``path``/``normalized_path`` plus scan metadata.
        edge_bootstraps: Optional pre-derived state-edge bootstrap requests,
            keyed by ``normalized_path``.

    Returns:
        One semantic ``SongIdentity`` locator per accepted entry, in input
        order; no generated or integer song id crosses this boundary.

    """
    file_ids = _upsert_batch(db, library, file_entries)

    if edge_bootstraps:
        identity_by_path = {
            entry["normalized_path"]: song
            for song, entry in zip(file_ids, file_entries, strict=True)
            if entry.get("normalized_path")
        }
        bootstrap_file_state_edges(db, edge_bootstraps, identity_by_path)

    return file_ids


def bootstrap_file_state_edges(
    db: Database,
    edge_bootstraps: list[dict[str, Any]],
    song_by_path: dict[str, SongIdentity],
) -> int:
    """Create ml_tagged state edges for songs that should skip ML tagging.

    Args:
        db: Persistence facade.
        edge_bootstraps: Bootstrap requests, each keyed by ``normalized_path``
            and a ``type`` discriminator.
        song_by_path: Mapping from ``normalized_path`` to the resolved
            ``SongIdentity`` locator. Entries missing from this mapping are
            skipped (``None``-skip semantics): a bootstrap whose song could not
            be resolved is a safe no-op and is never re-addressed by guesswork.

    Returns:
        The number of state edges created (skipped bootstraps do not count).

    """
    count = 0
    for bootstrap in edge_bootstraps:
        normalized_path = bootstrap["normalized_path"]
        song_identity = song_by_path.get(normalized_path)
        if song_identity is None:
            continue

        if bootstrap["type"] == "ml_tagged":
            transition_song_state(db, [song_identity], STATE_NOT_PROCESSED, STATE_PROCESSED)
            count += 1
    return count


def remove_deleted_files(db: Database, library: Library, paths: list[str]) -> int:
    """Bulk-delete files that are no longer on disk.

    Paths are resolved within the scanning library.  Relative paths can be
    shared by multiple libraries, so an unscoped lookup could delete another
    library's song.

    Returns the number of files deleted.

    Raises:
        ValueError: If ``library`` has no ``library_uuid`` to build a locator.

    """
    library_identity = _library_identity(library)
    removed = 0
    for path in paths:
        song = db.library.get_song_by_path(path, library)
        if song is None:
            continue
        command = SongRemoval(
            song_identity=SongIdentity(library=library_identity, normalized_path=song.normalized_path),
        )
        if db.library.remove_song(command):
            removed += 1
    return removed


def get_cached_folders(
    db: Database,
    library: Library,
) -> dict[str, LibraryFolder]:
    """Load all cached folder records for a library, keyed by relative path."""
    folders = db.library.list_folders_for_library(library)
    return {folder.path: folder for folder in folders}


def save_folder_record(
    db: Database,
    library: Library,
    rel_path: str,
    mtime: int,
    file_count: int,
) -> None:
    """Upsert a folder cache record matched by its library-scoped path."""
    folder = _folder_value(rel_path, mtime, file_count)
    # Replace in one transaction so a failed insert cannot leave the cache
    # missing after the old record has been deleted.
    existing = db.library.list_folders_for_library(library)
    if any(existing_folder.path == rel_path for existing_folder in existing):
        db.library.replace_library_folder(library, rel_path, folder)
    else:
        db.library.add_library_folder(library, folder)


def cleanup_stale_folders(
    db: Database,
    library: Library,
    existing_folder_rel_paths: set[str],
) -> None:
    """Delete folder cache records that no longer exist on disk."""
    try:
        cached_folders = get_cached_folders(db, library)
        stale_paths = [rel_path for rel_path in cached_folders if rel_path not in existing_folder_rel_paths]
        for stale_path in stale_paths:
            db.library.remove_library_folder(library, stale_path)
    except DatabaseStateError as e:
        logger.warning("[scan] Failed to clean up folder records: %s", e)
