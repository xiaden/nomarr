"""Library-file mutation helpers extracted from legacy persistence mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_file_query_comp import get_existing_file_paths
from nomarr.components.library.library_file_state_comp import (
    initialize_file_states,
    initialize_file_states_batch,
    transition_file_state,
)
from nomarr.components.library.library_id_comp import library_key_from_ref
from nomarr.helpers.constants.file_states import STATE_NOT_TAGGED, STATE_TAGGED
from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _normalize_file_id(file_ref: str) -> str:
    """Normalize a library-file reference to full document-id form."""
    return file_ref if file_ref.startswith("library_files/") else f"library_files/{file_ref}"


def _rebuild_library_file_links(
    db: Database,
    *,
    library_id: str,
    deleted_file_ids: set[str],
) -> None:
    """Rewrite one library's ownership edges without the deleted files."""
    existing_file_ids = db.library.list_library_file_ids(library_id)
    remaining_file_ids = [
        _normalize_file_id(file_id)
        for file_id in existing_file_ids
        if _normalize_file_id(file_id) not in deleted_file_ids
    ]
    db.library.delete_all_file_links_for_library(library_id)
    if remaining_file_ids:
        db.library.upsert_library_file_links_batch(
            [{"_from": library_id, "_to": file_id} for file_id in remaining_file_ids]
        )


def _delete_library_files(db: Database, file_ids: list[str]) -> None:
    """Delete library/app-managed state for the given file ids, then remove the docs."""
    normalized_file_ids = list(dict.fromkeys(_normalize_file_id(file_id) for file_id in file_ids))
    if not normalized_file_ids:
        return

    deleted_file_ids = set(normalized_file_ids)
    library_ids_by_file = db.library.get_library_ids_for_files(normalized_file_ids)
    library_ids = sorted({library_id for library_id in library_ids_by_file.values() if isinstance(library_id, str)})
    vector_namespaces = db.ml.list_registered_vector_namespaces()

    for file_id in normalized_file_ids:
        db.app.release_claim(file_id)
        db.library.delete_all_tags_for_file(file_id)
        for collection_name in vector_namespaces:
            db.ml.delete_vectors_for_file(collection_name, file_id)

    db.app.delete_file_state_edges(normalized_file_ids)

    for library_id in library_ids:
        _rebuild_library_file_links(db, library_id=library_id, deleted_file_ids=deleted_file_ids)

    for file_id in normalized_file_ids:
        db.library.delete_file(file_id)


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
    existing = cast("dict[str, Any] | None", db.library.get_file_by_path(absolute_path, library_id))
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
        file_id = cast("str", db.library.add_file(full_doc))
        initialize_file_states(db, file_id)
    else:
        file_id = str(existing["_id"])
        db.library.update_file(file_id, update_fields)

    db.library.link_file_to_library(library_id, file_id)
    if last_tagged_at is not None:
        transition_file_state(db, [file_id], STATE_NOT_TAGGED, STATE_TAGGED)
    return file_id


def delete_library_file(db: Database, file_id: str) -> None:
    """Delete one library-file document and its library/app-managed edges.

    Args:
        db: Database handle.
        file_id: ArangoDB document ID (``library_files/<key>``) or a raw file
            path. When a path is supplied it is resolved to the document ID
            first; returns early without error if no matching file is found.
    """
    if not file_id.startswith("library_files/"):
        file_doc: dict[str, Any] | None = None
        for library_doc in db.library.list_libraries():
            library_doc_id = library_doc.get("_id")
            if not isinstance(library_doc_id, str):
                continue
            file_doc = cast("dict[str, Any] | None", db.library.get_file_by_path(file_id, library_doc_id))
            if file_doc is not None:
                break
        if file_doc is None:
            return
        file_id = str(file_doc["_id"])

    _delete_library_files(db, [file_id])


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
    library_ids = [doc.get("library_id") for doc in file_docs]
    clean_docs = [{k: v for k, v in doc.items() if k != "library_id"} for doc in file_docs]

    # Identify which paths already exist before upserting so state edges are
    # only initialised for genuinely new files.  Re-initialising an existing
    # file would silently re-insert the negative-side edges for every axis
    # (e.g. not_tagged), overwriting transitions that have already occurred
    # and pushing those files backwards through the pipeline.
    paths = [d["path"] for d in clean_docs if "path" in d]
    existing_paths = get_existing_file_paths(db, paths)

    db.library.upsert_files_batch(clean_docs)

    resolved_library_ids: list[str] = []
    result: list[str] = []
    for library_id, doc in zip(library_ids, clean_docs, strict=True):
        if not isinstance(library_id, str):
            msg = "library_id is required for upsert_batch"
            raise ValueError(msg)
        file_doc = cast("dict[str, Any] | None", db.library.get_file_by_path(str(doc["path"]), library_id))
        if file_doc is None:
            msg = f"Upserted file could not be reloaded by path: {doc.get('path')}"
            raise RuntimeError(msg)
        resolved_library_ids.append(library_id)
        result.append(str(file_doc["_id"]))

    edge_docs = [
        {"_from": library_id, "_to": file_id} for library_id, file_id in zip(resolved_library_ids, result, strict=True)
    ]
    if edge_docs:
        db.library.upsert_library_file_links_batch(edge_docs)
    new_file_ids = [
        file_id for file_id, doc in zip(result, clean_docs, strict=True) if doc.get("path") not in existing_paths
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
    db.library.update_file(file_id, update_dict)


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


def update_metadata_cache_batch(db: Database, updates: list[dict[str, Any]]) -> None:
    """Batch-update embedded metadata-cache fields for many songs.

    Args:
        db: Database handle.
        updates: List of metadata update payloads. Each dict must contain
            ``song_id`` (``str``; document ``_id`` of the library file) and
            may contain ``artist`` (``str | None``), ``artists``
            (``list[str] | None``), ``album`` (``str | None``), ``labels``
            (``list[str] | None``), ``genres`` (``list[str] | None``), and
            ``year`` (``int | None``).
    """
    if not updates:
        return
    for entry in updates:
        db.library.update_file(
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
    file_docs = [
        file_doc
        for path in paths
        if (file_doc := cast("dict[str, Any] | None", db.library.get_file_by_path_unscoped(path))) is not None
    ]
    file_ids = [str(d["_id"]) for d in file_docs]
    if not file_ids:
        return 0

    _delete_library_files(db, file_ids)
    return len(file_ids)


def get_file_library_key(db: Database, file_id: str) -> str | None:
    """Return the owning library key for a file id."""
    library_ids_by_file = db.library.get_library_ids_for_files([file_id])
    library_id = library_ids_by_file.get(_normalize_file_id(file_id))
    if library_id is None:
        return None
    return library_key_from_ref(library_id)


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
