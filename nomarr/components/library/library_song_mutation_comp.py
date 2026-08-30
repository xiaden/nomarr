"""Library song mutation helpers extracted from legacy persistence mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dto import LibraryPath
    from nomarr.persistence.db import Database


def upsert_library_song(
    db: Database,
    path: LibraryPath,
    library: Library,
    file_size: int,
    modified_time: int,
    duration_seconds: float | None = None,
    last_tagged_at: int | None = None,
) -> int:
    """Insert or update a library-song document and its ownership/state edges.

    Args:
        db: Database instance.
        path: Validated ``LibraryPath`` for the song.
        library: Domain ``Library`` (natural identity) that owns the song.
        file_size: File size in bytes.
        modified_time: File mtime in ms since epoch.
        duration_seconds: Optional audio duration.
        last_tagged_at: Optional wall-clock timestamp of last tag write.

    Raises ValueError if the path is not valid.
    """
    if not path.is_valid():
        msg = f"Cannot upsert invalid path ({path.status}): {path.reason}"
        raise ValueError(msg)

    scanned_at = now_ms().value
    normalized_path = str(path.relative)
    absolute_path = str(path.absolute)
    return db.library.add_song_to_library(
        library,
        {
            "path": absolute_path,
            "normalized_path": normalized_path,
            "file_size": file_size,
            "modified_time": modified_time,
            "duration_seconds": duration_seconds,
            "scanned_at": scanned_at,
            "chromaprint": None,
            "last_tagged_at": last_tagged_at,
        },
    )


def delete_library_song(db: Database, path: str, library: Library) -> None:
    """Delete a library-song document and its edges.

    The song is addressed by its natural ``(library, path)`` identity — the
    composite key the ``songs`` table guarantees unique. The storage primary key
    is never exposed to or interpreted by this component, so a numeric-looking
    path is still treated as a path, never as a database id. No-op when no song
    exists at the path.
    """
    db.library.remove_song_by_path(path, library)


def update_song_path(
    db: Database,
    song_id: int,
    new_path: str,
    file_size: int,
    modified_time: int,
    duration_seconds: float | None = None,
    normalized_path: str | None = None,
) -> None:
    """Update path and metadata for a moved song."""
    db.library.update_library_song_path(song_id, new_path)
    db.library.update_library_song_scan_metadata(
        song_id,
        file_size=file_size,
        modified_time=modified_time,
        duration_seconds=duration_seconds,
        normalized_path=normalized_path,
    )


def update_song_modified_time(db: Database, file_key: int, modified_time_ms: int) -> None:
    """Update the stored modified-time after a successful file write."""
    db.library.update_library_song_modified_time(file_key, modified_time_ms)


def bulk_delete_songs(db: Database, paths: list[str], library: Library) -> int:
    """Delete multiple library-song documents by path in one library.

    Songs are addressed by their natural ``(library, path)`` identity; the
    storage primary key is never interpreted by this component. Silently skips
    paths with no matching document. Returns the number deleted.
    """
    if not paths:
        return 0

    resolved = [path for path in paths if db.library.get_song_by_path(path, library) is not None]
    matched_paths = list(dict.fromkeys(resolved))
    if not matched_paths:
        return 0

    for path in matched_paths:
        db.library.remove_song_by_path(path, library)
    return len(matched_paths)


def get_song_library_key(db: Database, song_id: int) -> int | None:
    """Return the owning library id for a song id.

    PostgreSQL returns integer library ids directly (no ``libraries/`` prefix).
    """
    library_ids = db.library.get_library_ids_for_songs([song_id])
    return library_ids.get(song_id)


def set_chromaprint(db: Database, song_id: int, chromaprint: str) -> None:
    """Persist a chromaprint fingerprint for one song."""
    db.library.set_library_song_chromaprint(song_id, chromaprint)


def update_last_tagged_at(db: Database, song_id: int) -> None:
    """Record the wall-clock time at which a song was tagged."""
    db.library.update_library_song_last_tagged_at(song_id, now_ms().value)
