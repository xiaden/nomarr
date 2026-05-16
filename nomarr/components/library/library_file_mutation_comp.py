"""Library-file mutation helpers extracted from legacy persistence mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_id_comp import library_key_from_ref
from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _normalize_file_id(file_ref: str) -> str:
    """Normalize a library-file reference to full document-id form."""
    return file_ref if file_ref.startswith("library_files/") else f"library_files/{file_ref}"


def upsert_library_file(
    db: Database,
    path: LibraryPath,
    library_id: str,
    file_size: int,
    modified_time: int,
    duration_seconds: float | None = None,
    artist: str | None = None,
    album: str | None = None,
    title: str | None = None,
    last_tagged_at: int | None = None,
) -> str:
    """Insert or update one library-file document plus its ownership/state edges.

    Args:
        db: Database handle used for the document and edge upserts.
        path: Validated library path for the file being inserted or updated.
        library_id: Full ``_id`` of the owning library document.
        file_size: File size in bytes to persist on the library-file document.
        modified_time: File modified timestamp in milliseconds.
        duration_seconds: Optional audio duration in seconds.
        artist: Optional cached artist metadata.
        album: Optional cached album metadata.
        title: Optional cached title metadata.
        last_tagged_at: Optional marker indicating the file was already tagged.

    Returns:
        The ``_id`` string of the upserted file document.

    Raises:
        ValueError: If ``path.is_valid()`` returns ``False``.
    """
    if not path.is_valid():
        msg = f"Cannot upsert invalid path ({path.status}): {path.reason}"
        raise ValueError(msg)

    scanned_at = now_ms().value
    normalized_path = str(path.relative)
    absolute_path = str(path.absolute)
    library_key = library_key_from_ref(library_id)
    return db.library.add_file_to_library(
        library_id,
        {
            "path": absolute_path,
            "library_key": library_key,
            "normalized_path": normalized_path,
            "file_size": file_size,
            "modified_time": modified_time,
            "duration_seconds": duration_seconds,
            "artist": artist,
            "album": album,
            "title": title,
            "scanned_at": scanned_at,
            "chromaprint": None,
            "last_tagged_at": last_tagged_at,
        },
    )


def delete_library_file(db: Database, file_id: str) -> None:
    """Delete one library-file document and its library/app-managed edges.

    Args:
        db: Database handle.
        file_id: ArangoDB document ID (``library_files/<key>``) or a raw file
            path. When a path is supplied it is resolved to the document ID
            first; returns early without error if no matching file is found.
    """
    if not file_id.startswith("library_files/"):
        db.library.remove_file_by_path(file_id)
        return

    db.library.remove_file(file_id)


def upsert_batch(db: Database, file_docs: list[dict[str, Any]]) -> list[str]:
    """Batch-upsert library files, ownership edges, and initial state edges.

    Args:
        db: Database handle used for the batch document and edge upserts.
        file_docs: Library-file payloads where each dict must include a ``library_id``
            key plus the fields accepted by the single-file upsert schema, such as
            ``path``, ``file_size``, ``modified_time``, and optional metadata.

    Returns:
        List of ``_id`` strings for the upserted files, in the same order as the input.
    """
    if not file_docs:
        return []

    grouped_docs: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, file_doc in enumerate(file_docs):
        library_id = file_doc.get("library_id")
        if not isinstance(library_id, str):
            msg = "library_id is required for upsert_batch"
            raise ValueError(msg)
        grouped_docs.setdefault(library_id, []).append(
            (index, {k: v for k, v in file_doc.items() if k != "library_id"})
        )

    result = [""] * len(file_docs)
    for library_id, entries in grouped_docs.items():
        payloads = [payload for _, payload in entries]
        file_ids = db.library.add_files_to_library(library_id, payloads)
        if len(file_ids) != len(entries):
            msg = f"add_files_to_library() returned {len(file_ids)} ids for {len(entries)} payloads"
            raise RuntimeError(msg)
        for (index, _), file_id in zip(entries, file_ids, strict=True):
            result[index] = file_id
    return result


def update_file_path(
    db: Database,
    file_id: str,
    new_path: str,
    file_size: int,
    modified_time: int,
    artist: str | None = None,
    album: str | None = None,
    title: str | None = None,
    duration_seconds: float | None = None,
    normalized_path: str | None = None,
) -> None:
    """Update path and metadata for a moved file."""
    db.library.update_library_file_path(file_id, new_path)
    fields: dict[str, Any] = {
        "file_size": file_size,
        "modified_time": modified_time,
        "is_valid": 1,
        "artist": artist,
        "album": album,
        "title": title,
        "duration_seconds": duration_seconds,
        "scanned_at": now_ms().value,
    }
    if normalized_path is not None:
        fields["normalized_path"] = normalized_path
    db.library.update_file(file_id, fields)


def update_file_modified_time(db: Database, file_key: str, modified_time_ms: int) -> None:
    """Update the stored modified-time after a successful file write."""
    db.library.update_file(_normalize_file_id(file_key), {"modified_time": modified_time_ms})


def update_metadata_cache(
    db: Database,
    song_id: str,
    *,
    artist: str | None,
    artists: list[str] | None,
    album: str | None,
    labels: list[str] | None,
    genres: list[str] | None,
    year: int | None,
) -> None:
    """Update embedded metadata-cache fields for one song."""
    db.library.update_file(
        song_id,
        {
            "artist": artist,
            "artists": artists,
            "album": album,
            "labels": labels,
            "genres": genres,
            "year": year,
        },
    )


def bulk_delete_files(db: Database, paths: list[str]) -> int:
    """Delete multiple library-file documents and their library/app-managed edges.

    Resolves each supplied path to a file document, silently skips paths with
    no matching document, and returns early with ``0`` when ``paths`` is empty.

    Args:
        db: Database handle.
        paths: File paths to resolve and delete. Paths with no matching file
            document are ignored.

    Returns:
        The number of files that were found and deleted.
    """
    if not paths:
        return 0

    matched_paths = list(
        dict.fromkeys(
            path
            for path in paths
            if cast("dict[str, Any] | None", db.library.find_file_by_path_any_library(path)) is not None
        )
    )
    if not matched_paths:
        return 0

    for path in matched_paths:
        db.library.remove_file_by_path(path)
    return len(matched_paths)


def get_file_library_key(db: Database, file_id: str) -> str | None:
    """Return the owning library key for a file id."""
    normalized = _normalize_file_id(file_id)
    library_ids = db.library.get_library_ids_for_files([normalized])
    library_id = library_ids.get(normalized)
    if library_id is None:
        return None
    # library_id is like "libraries/10286" — extract the key after the slash
    parts = library_id.split("/", 1)
    return parts[1] if len(parts) == 2 else library_id


def set_chromaprint(db: Database, file_id: str, chromaprint: str) -> None:
    """Persist a chromaprint fingerprint for one file."""
    db.library.update_file(_normalize_file_id(file_id), {"chromaprint": chromaprint})


def update_last_tagged_at(db: Database, file_id: str) -> None:
    """Record the wall-clock time at which a file was tagged.

    Args:
        db: Database handle.
        file_id: Document ``_id`` of the library-file to update.

    """
    db.library.update_file(file_id, {"last_tagged_at": now_ms().value})
