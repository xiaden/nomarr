"""Library song mutation helpers extracted from legacy persistence mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dto import LibraryPath
    from nomarr.persistence.db import Database


def _normalize_song_id(file_ref: str) -> str:
    """Normalize a library-song reference to string form.

    PostgreSQL uses integer IDs; file_ref is already the string representation.
    """
    return file_ref


def upsert_library_song(
    db: Database,
    path: LibraryPath,
    library_id: int,
    file_size: int,
    modified_time: int,
    duration_seconds: float | None = None,
    last_tagged_at: int | None = None,
) -> int:
    """Insert or update a library-song document and its ownership/state edges.

    Raises ValueError if the path is not valid.
    """
    if not path.is_valid():
        msg = f"Cannot upsert invalid path ({path.status}): {path.reason}"
        raise ValueError(msg)

    scanned_at = now_ms().value
    normalized_path = str(path.relative)
    absolute_path = str(path.absolute)
    return db.library.add_song_to_library(
        library_id,
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


def delete_library_song(db: Database, song_id: int | str, library_id: int | None = None) -> None:
    """Delete a library-song document and its edges.

    Accepts a song ID (integer) or a raw file path (resolved via path lookup).
    No-op if the file is not found.
    """
    # Try to interpret as integer ID first
    try:
        int(song_id)
        # It's a numeric ID, use it directly
        db.library.remove_song(song_id)
    except ValueError as err:
        # Not an integer, treat as path
        if library_id is None:
            raise ValueError("library_id is required when deleting a song by path") from err
        db.library.remove_song_by_path(str(song_id), library_id)


def upsert_batch(db: Database, file_docs: list[dict[str, Any]]) -> list[int]:
    """Batch-upsert library songs with ownership edges.

    Each file_doc must include a ``library_id`` key. Returns id integers in
    input order.
    """
    if not file_docs:
        return []

    grouped_docs: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for index, file_doc in enumerate(file_docs):
        library_id = file_doc.get("library_id")
        if not isinstance(library_id, int):
            msg = "library_id is required for upsert_batch"
            raise ValueError(msg)
        grouped_docs.setdefault(library_id, []).append(
            (index, {k: v for k, v in file_doc.items() if k != "library_id"})
        )

    result = [0] * len(file_docs)
    for library_id, entries in grouped_docs.items():
        payloads = [payload for _, payload in entries]
        song_ids = db.library.add_songs_to_library(library_id, payloads)
        if len(song_ids) != len(entries):
            msg = f"add_files_to_library() returned {len(song_ids)} ids for {len(entries)} payloads"
            raise RuntimeError(msg)
        for (index, _), song_id in zip(entries, song_ids, strict=True):
            result[index] = song_id
    return result


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


def bulk_delete_songs(db: Database, paths: list[str], library_id: int) -> int:
    """Delete multiple library-song documents by path in one library.

    Silently skips paths with no matching document. Returns the number deleted.
    """
    if not paths:
        return 0

    resolved = [
        path
        for path in paths
        if cast("dict[str, Any] | None", db.library.get_song_by_path(path, library_id)) is not None
    ]
    matched_paths = list(dict.fromkeys(resolved))
    if not matched_paths:
        return 0

    for path in matched_paths:
        db.library.remove_song_by_path(path, library_id)
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
