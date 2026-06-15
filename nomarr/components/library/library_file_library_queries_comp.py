"""Library-scoped query helpers for aggregate/folder/chromaprint operations.

Extracted from ``library_file_query_comp`` during the Phase 4 oversized-file
split.  Owns all query logic that is scoped to a library context (per-library
statistics, folder membership, and library-level lookups).
"""

from __future__ import annotations

from typing import Any, cast

# Re-exported from library_file_query_comp to keep the dependency one-way.
from nomarr.components.library.library_file_query_comp import (
    _get_all_library_file_docs,
    _library_file_docs_for_library,
)
from nomarr.components.library.library_file_state_comp import count_untagged_files
from nomarr.components.library.library_file_tag_queries_comp import _tags_by_name
from nomarr.components.library.library_id_comp import normalize_library_id
from nomarr.helpers.constants.file_states import STATE_PROCESSED
from nomarr.persistence.db import Database

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _numeric_value(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _path_parent(path_value: Any) -> str | None:
    if not isinstance(path_value, str):
        return None
    return path_value.rsplit("/", 1)[0] if "/" in path_value else ""


def _matches_folder_rel_path(normalized_path: Any, folder_rel_path: str) -> bool:
    if not isinstance(normalized_path, str):
        return False
    if folder_rel_path == "":
        return "/" not in normalized_path
    return normalized_path.startswith(f"{folder_rel_path}/")


def _library_id_from_file_doc(file_doc: dict[str, Any]) -> str | None:
    library_key = file_doc.get("library_key")
    return normalize_library_id(library_key) if isinstance(library_key, str) else None


def _hydrate_files_with_tagged_state(db: Database, file_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate file docs with ``has_tagged_state`` derived from ``file_has_state`` edges."""
    file_ids = [file_id for file_doc in file_docs if isinstance((file_id := file_doc.get("_id")), str)]
    if not file_ids:
        return list(file_docs)

    tagged_file_ids = set(db.app.list_files_in_state(STATE_PROCESSED, limit=None))

    return [
        {**file_doc, "has_tagged_state": file_id in tagged_file_ids}
        if isinstance((file_id := file_doc.get("_id")), str)
        else dict(file_doc)
        for file_doc in file_docs
    ]


# ---------------------------------------------------------------------------
# Folder queries
# ---------------------------------------------------------------------------


def get_folder_rel_paths(db: Database, library_id: str) -> set[str]:
    """Get cached folder relative paths for one library."""
    return {
        folder_doc["path"]
        for folder_doc in db.library.list_folders_for_library(normalize_library_id(library_id))
        if isinstance(folder_doc.get("path"), str)
    }


def get_files_for_folder(
    db: Database,
    library_id: str,
    folder_rel_path: str,
) -> dict[str, dict[str, Any]]:
    """Get file documents for a single folder."""
    file_docs = db.library.list_library_files_for_folder(normalize_library_id(library_id), folder_rel_path)
    return {file_doc["path"]: file_doc for file_doc in file_docs if isinstance(file_doc.get("path"), str)}


def get_files_for_folders(
    db: Database,
    library_id: str,
    folder_rel_paths: list[str],
) -> dict[str, dict[str, Any]]:
    """Batch-fetch file documents for multiple folders.

    TODO(migrate): fetches all files for the library then filters by
    normalized_path prefix in Python. Persistence needs a multi-folder AQL
    query so this doesn't load the entire library into memory.
    """
    if not folder_rel_paths:
        return {}
    file_docs = _hydrate_files_with_tagged_state(db, _library_file_docs_for_library(db, library_id))
    return {
        file_doc["path"]: file_doc
        for file_doc in file_docs
        if isinstance(file_doc.get("path"), str)
        and any(
            _matches_folder_rel_path(file_doc.get("normalized_path"), folder_rel_path)
            for folder_rel_path in folder_rel_paths
        )
    }


def find_move_candidate_by_chromaprint(
    db: Database,
    library_id: str,
    chromaprint: str,
) -> dict[str, Any] | None:
    """Return the library file matching ``chromaprint``, or ``None``. Used for DB-lookup move detection."""
    result = db.library.find_library_file_by_chromaprint(normalize_library_id(library_id), chromaprint)
    return cast("dict[str, Any] | None", result)


# ---------------------------------------------------------------------------
# Library statistics
# ---------------------------------------------------------------------------


def get_library_stats(db: Database, library_id: str | None = None) -> dict[str, Any]:
    """Get aggregate library-file statistics.

    TODO(migrate): loads all files (and all tags when library_id is set) into
    Python to compute duration/size sums and distinct artist/album counts.
    Should be replaced by an AQL aggregation query.
    """
    if library_id is not None:
        file_docs = _library_file_docs_for_library(db, library_id)
        total_files = db.library.count_library_file_links(normalize_library_id(library_id))
        file_ids = [doc["_id"] for doc in file_docs if isinstance(doc.get("_id"), str)]
        tags_by_file = db.library.list_file_tags_for_files(file_ids)
        total_artists = len(
            {
                tag_doc["value"]
                for tag_docs in tags_by_file.values()
                for tag_doc in tag_docs
                if tag_doc.get("name") == "artist"
            }
        )
        total_albums = len(
            {
                tag_doc["value"]
                for tag_docs in tags_by_file.values()
                for tag_doc in tag_docs
                if tag_doc.get("name") == "album"
            }
        )
    else:
        file_docs = _get_all_library_file_docs(db, None)
        total_files = db.library.count_files()
        total_artists = len(_tags_by_name(db, "artist"))
        total_albums = len(_tags_by_name(db, "album"))

    result: dict[str, Any] = {
        "total_files": total_files,
        "total_artists": total_artists,
        "total_albums": total_albums,
        "total_duration": sum(_numeric_value(file_doc.get("duration_seconds")) for file_doc in file_docs),
        "total_size": int(sum(_numeric_value(file_doc.get("file_size")) for file_doc in file_docs)),
    }

    result["needs_tagging_count"] = count_untagged_files(db, library_id)
    return result


def get_library_counts(db: Database) -> dict[str, dict[str, int]]:
    """Get file and folder counts for all libraries.

    TODO(migrate): loads all files per library to derive folder_count by
    computing unique path parents in Python. Persistence should expose
    db.library.get_library_file_and_folder_counts() returning
    dict[library_id, {file_count, folder_count}] via a single AQL query.
    """
    result: dict[str, dict[str, int]] = {}
    for library_key in db.library.list_library_keys():
        library_id = normalize_library_id(library_key)
        file_docs = db.library.list_library_files(library_id, limit=None)
        folder_paths = {parent for file_doc in file_docs if (parent := _path_parent(file_doc.get("path"))) is not None}
        result[library_id] = {
            "file_count": len(file_docs),
            "folder_count": len(folder_paths),
        }
    return result


def get_artist_album_frequencies(db: Database, limit: int) -> dict[str, list[tuple[str, int]]]:
    """Get artist/album frequency rows for analytics views."""
    frequencies = db.library.list_tag_value_frequencies(["artist", "album"], limit)
    return {
        "artist_rows": frequencies.get("artist", []),
        "album_rows": frequencies.get("album", []),
    }


# ---------------------------------------------------------------------------
# Destructive reset
# ---------------------------------------------------------------------------


def clear_library_data(db: Database) -> None:
    """Nuke all library-file data by truncating every affected collection.

    This is a destructive full-reset.  Rather than paying per-document cascade
    cost, we truncate every collection that holds library-file-derived data in
    one pass.  Exception: ``ml_output_streams`` documents are deleted per-file
    rather than truncated, so their linked ``file_has_output_stream`` and
    ``output_has_stream`` edges are also removed. Order: deepest derived data
    first, then edges, then documents.
    """
    # Derived data
    from nomarr.components.ml.inference.ml_output_stream_store_comp import delete_output_streams

    for collection_name in db.ml.list_vector_collection_names():
        db.ml.clear_vector_collection(collection_name)
    for file_doc in cast("list[dict[str, Any]]", db.library.list_files(limit=None)):
        file_id = file_doc.get("_id")
        if isinstance(file_id, str):
            delete_output_streams(db, file_id)
    # Link/edge collections
    db.ml.clear_vector_links()
    db.library.clear_song_tags()
    db.app.clear_file_state_links()
    db.library.clear_file_links()
    db.library.clear_folder_links()
    db.app.clear_library_scan_links()
    db.app.clear_pipeline_state_links()
    # Documents
    db.library.clear_tags()
    db.library.clear_files()
    db.library.clear_folders()
    db.app.clear_scans()


# ---------------------------------------------------------------------------
# Chromaprint queries
# ---------------------------------------------------------------------------


def get_files_by_chromaprint(
    db: Database,
    chromaprint: str,
    library_id: str | None = None,
) -> list[dict[str, Any]]:
    """Get files whose stored chromaprint matches the supplied value.

    TODO(migrate): library_id branch fetches all library files then filters by
    chromaprint in Python. Use db.library.find_library_file_by_chromaprint()
    (which already exists) and wrap in a list for the scoped path.
    """
    if library_id is not None:
        return [
            file_doc
            for file_doc in _library_file_docs_for_library(db, library_id)
            if file_doc.get("chromaprint") == chromaprint
        ]

    return cast(
        "list[dict[str, Any]]",
        db.library.list_files(filters={"chromaprint": chromaprint}, limit=None),
    )
