"""Library-file mutation helpers extracted from legacy persistence mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_file_query_comp import get_existing_file_paths
from nomarr.components.library.library_file_state_comp import (
    clear_all_states,
    clear_all_states_batch,
    initialize_file_states,
    initialize_file_states_batch,
    transition_file_state,
)
from nomarr.components.ml.inference.ml_segment_stats_store_comp import (
    delete_segment_stats_for_file,
    delete_segment_stats_for_files,
)
from nomarr.helpers.constants.file_states import STATE_NOT_TAGGED, STATE_TAGGED
from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


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
    library_key = library_id.split("/", 1)[1] if "/" in library_id else library_id
    existing = cast("dict[str, Any] | None", db.library_files.path.get(absolute_path))
    update_fields = {
        "library_key": library_key,
        "normalized_path": normalized_path,
        "file_size": file_size,
        "modified_time": modified_time,
        "duration_seconds": duration_seconds,
        "artist": artist,
        "album": album,
        "title": title,
        "scanned_at": scanned_at,
    }
    if existing is None:
        full_doc = {
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
        }
        file_id = db.library_files.insert([full_doc])[0]
        initialize_file_states(db, file_id)
    else:
        file_id = str(existing["_id"])
        db.library_files._id.update(file_id, update_fields)

    db.library_contains_file._to.upsert(
        [{"_from": library_id, "_to": file_id}],
        match_field=["_from", "_to"],
    )
    if last_tagged_at is not None:
        transition_file_state(db, [file_id], STATE_NOT_TAGGED, STATE_TAGGED)
    return file_id


def delete_library_file(db: Database, file_id: str) -> None:
    """Delete one file and its directly-derived data/edges."""
    if not file_id.startswith("library_files/"):
        file_doc = cast("dict[str, Any] | None", db.library_files.path.get(file_id))
        if file_doc is None:
            return
        file_id = str(file_doc["_id"])

    db.delete_vectors_by_file_id(file_id)
    delete_segment_stats_for_file(db, file_id)
    db.song_has_tags._from.delete(file_id)
    clear_all_states(db, file_id)
    db.library_contains_file._to.delete(file_id)
    db.library_files.delete([file_id])


def upsert_batch(db: Database, file_docs: list[dict[str, Any]]) -> list[str]:
    """Batch-upsert library files, ownership edges, and initial state edges.

    Args:
        db: Database handle used for the batch document and edge upserts.
        file_docs: Library-file payloads where each dict must include a ``library_id`` key plus the fields accepted by the single-file upsert schema, such as ``path``, ``file_size``, ``modified_time``, and optional metadata.

    Returns:
        List of ``_id`` strings for the upserted files, in the same order as the input.
    """
    if not file_docs:
        return []
    library_ids = [doc.get("library_id") for doc in file_docs]
    clean_docs = [{k: v for k, v in doc.items() if k != "library_id"} for doc in file_docs]

    # Identify which paths already exist before upserting so state edges are
    # only initialised for genuinely new files.  Re-initialising an existing
    # file would silently re-insert the negative-side edges for every axis
    # (e.g. not_tagged), overwriting transitions that have already occurred
    # and pushing those files backwards through the pipeline.
    paths = [d["path"] for d in clean_docs if "path" in d]
    existing_paths = get_existing_file_paths(db, paths)

    result = db.library_files.path.upsert(clean_docs, match_field="path")

    edge_docs = [
        {"_from": lib_id, "_to": file_id}
        for lib_id, file_id in zip(library_ids, result, strict=True)
        if lib_id is not None
    ]
    if edge_docs:
        db.library_contains_file._to.upsert(
            edge_docs,
            match_field=["_from", "_to"],
        )
    new_file_ids = [
        file_id
        for file_id, doc in zip(result, clean_docs, strict=True)
        if doc.get("path") not in existing_paths
    ]
    initialize_file_states_batch(db, new_file_ids)
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
    scanned_at = now_ms().value
    update_dict: dict[str, Any] = {
        "path": new_path,
        "file_size": file_size,
        "modified_time": modified_time,
        "is_valid": 1,
        "artist": artist,
        "album": album,
        "title": title,
        "duration_seconds": duration_seconds,
        "scanned_at": scanned_at,
    }
    if normalized_path is not None:
        update_dict["normalized_path"] = normalized_path
    db.library_files._id.update(file_id, update_dict)


def update_file_modified_time(db: Database, file_key: str, modified_time_ms: int) -> None:
    """Update the stored modified-time after a successful file write."""
    db.library_files._key.update(file_key, {"modified_time": modified_time_ms})


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
    db.library_files._id.update(
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


def update_metadata_cache_batch(db: Database, updates: list[dict[str, Any]]) -> None:
    """Batch-update embedded metadata-cache fields for many songs."""
    if not updates:
        return
    for entry in updates:
        db.library_files._id.update(
            str(entry["song_id"]),
            {
                "artist": entry.get("artist"),
                "artists": entry.get("artists"),
                "album": entry.get("album"),
                "labels": entry.get("labels"),
                "genres": entry.get("genres"),
                "year": entry.get("year"),
            },
        )


def bulk_delete_files(db: Database, paths: list[str]) -> int:
    """Delete multiple files by path and clean up their derived data."""
    if not paths:
        return 0
    file_docs = db.library_files.path.get.in_(paths)
    file_ids = [str(d["_id"]) for d in file_docs]
    if file_ids:
        db.delete_vectors_by_file_ids(file_ids)
        delete_segment_stats_for_files(db, file_ids)
        for file_id in file_ids:
            db.song_has_tags._from.delete(file_id)
        clear_all_states_batch(db, file_ids)
        for file_id in file_ids:
            db.library_contains_file._to.delete(file_id)

    if file_ids:
        db.library_files.delete(file_ids)
    return len(file_ids)


def get_file_library_key(db: Database, file_id: str) -> str | None:
    """Return the owning library key for a file id."""
    results = db.library_contains_file._to.get.many(file_id, limit=1)
    if not results:
        return None
    edge = results[0]
    library_id = str(edge["_from"])
    return library_id.split("/", 1)[1] if "/" in library_id else library_id


def set_chromaprint(db: Database, file_id: str, chromaprint: str) -> None:
    """Persist a chromaprint fingerprint for one file."""
    doc_key = file_id.split("/", 1)[1] if "/" in file_id else file_id
    db.library_files._key.update(doc_key, {"chromaprint": chromaprint})
