"""Library-file mutation helpers extracted from legacy persistence mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_id_comp import library_key_from_ref
from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _normalize_file_id(file_ref: str) -> str:
    """Normalize a library-file reference to string form.

    PostgreSQL uses integer IDs; file_ref is already the string representation.
    """
    return file_ref


async def upsert_library_file(
    db: Database,
    path: LibraryPath,
    library_id: int,
    file_size: int,
    modified_time: int,
    duration_seconds: float | None = None,
    last_tagged_at: int | None = None,
) -> int:
    """Insert or update a library-file document and its ownership/state edges.

    Raises ValueError if the path is not valid.
    """
    if not path.is_valid():
        msg = f"Cannot upsert invalid path ({path.status}): {path.reason}"
        raise ValueError(msg)

    scanned_at = now_ms().value
    normalized_path = str(path.relative)
    absolute_path = str(path.absolute)
    library_key = library_key_from_ref(library_id)
    return await db.library.add_file_to_library(
        library_id,
        {
            "path": absolute_path,
            "library_key": library_key,
            "normalized_path": normalized_path,
            "file_size": file_size,
            "modified_time": modified_time,
            "duration_seconds": duration_seconds,
            "scanned_at": scanned_at,
            "chromaprint": None,
            "last_tagged_at": last_tagged_at,
        },
    )


async def delete_library_file(db: Database, file_id: int) -> None:
    """Delete a library-file document and its edges.

    Accepts a file ID (integer) or a raw file path (resolved via path lookup).
    No-op if the file is not found.
    """
    # Try to interpret as integer ID first
    try:
        int(file_id)
        # It's a numeric ID, use it directly
        await db.library.remove_file(file_id)
    except ValueError:
        # Not an integer, treat as path
        await db.library.remove_file_by_path(file_id)


async def upsert_batch(db: Database, file_docs: list[dict[str, Any]]) -> list[int]:
    """Batch-upsert library files with ownership edges.

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
        file_ids = await db.library.add_files_to_library(library_id, payloads)
        if len(file_ids) != len(entries):
            msg = f"add_files_to_library() returned {len(file_ids)} ids for {len(entries)} payloads"
            raise RuntimeError(msg)
        for (index, _), file_id in zip(entries, file_ids, strict=True):
            result[index] = file_id
    return result


async def update_file_path(
    db: Database,
    file_id: int,
    new_path: str,
    file_size: int,
    modified_time: int,
    duration_seconds: float | None = None,
    normalized_path: str | None = None,
) -> None:
    """Update path and metadata for a moved file."""
    await db.library.update_library_file_path(file_id, new_path)
    fields: dict[str, Any] = {
        "file_size": file_size,
        "modified_time": modified_time,
        "is_valid": 1,
        "duration_seconds": duration_seconds,
        "scanned_at": now_ms().value,
    }
    if normalized_path is not None:
        fields["normalized_path"] = normalized_path
    db.library.file_repo.update_file(file_id, fields)


async def update_file_modified_time(db: Database, file_key: int, modified_time_ms: int) -> None:
    """Update the stored modified-time after a successful file write."""
    await db.library.update_library_file_modified_time(file_key, modified_time_ms)


async def bulk_delete_files(db: Database, paths: list[str]) -> int:
    """Delete multiple library-file documents by path.

    Silently skips paths with no matching document. Returns the number deleted.
    """
    if not paths:
        return 0

    matched_paths = list(
        dict.fromkeys(
            path
            for path in paths
            if cast("dict[str, Any] | None", await db.library.find_file_by_path_any_library(path)) is not None
        )
    )
    if not matched_paths:
        return 0

    for path in matched_paths:
        await db.library.remove_file_by_path(path)
    return len(matched_paths)


async def get_file_library_key(db: Database, file_id: int) -> int | None:
    """Return the owning library id for a file id.

    PostgreSQL returns integer library ids directly (no ``libraries/`` prefix).
    """
    library_ids = await db.library.get_library_ids_for_files([file_id])
    return library_ids.get(file_id)


async def set_chromaprint(db: Database, file_id: int, chromaprint: int) -> None:
    """Persist a chromaprint fingerprint for one file."""
    await db.library.set_library_file_chromaprint(file_id, chromaprint)


async def update_last_tagged_at(db: Database, file_id: int) -> None:
    """Record the wall-clock time at which a file was tagged."""
    await db.library.update_library_file_last_tagged_at(file_id, now_ms().value)
