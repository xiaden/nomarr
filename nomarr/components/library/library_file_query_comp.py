"""Library-file query helpers extracted from legacy persistence mixins.

These helpers own the complex multi-hop reads that are no longer methods on
the constructor-backed ``db.library_files`` namespace.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Literal, cast

from nomarr.components.library.library_file_state_comp import count_untagged_files
from nomarr.helpers.constants.file_states import STATE_TAGGED
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.base import Field
from nomarr.persistence.constructor.pagination import DEFAULT_LIMIT
from nomarr.persistence.db import Database


def get_file_by_id(db: Database, file_id: str) -> dict[str, Any] | None:
    """Get one library-file document by ``_id``."""
    return cast("dict[str, Any] | None", db.library_files.get(_id=file_id))


def count_recently_tagged(db: Database, window_seconds: int = 300) -> int:
    """Count files whose ``last_tagged_at`` timestamp falls within the recent window.

    Args:
        db: Database instance.
        window_seconds: How far back to look (default 5 minutes).

    Returns:
        Number of files tagged within the window.

    """
    cutoff_ms = now_ms().value - window_seconds * 1000
    docs = cast(
        "list[dict[str, Any]]",
        db.library_files.get.gte("last_tagged_at", cutoff_ms),
    )
    return len(docs)


def get_existing_file_paths(db: Database, paths: list[str]) -> set[str]:
    """Return the subset of *paths* that already have a record in the library-files collection.

    Used before batch-upsert operations to identify genuinely new files so that
    state initialisation is only applied once per file — on first insertion.

    Args:
        db: Database instance.
        paths: Absolute file paths to check.

    Returns:
        Set of paths (subset of *paths*) that exist in the database.
    """
    if not paths:
        return set()
    return {
        str(doc["path"])
        for doc in cast("list[dict[str, Any]]", db.library_files.get.in_(Field("path", paths)))
        if "path" in doc
    }


def _normalize_library_id(library_id: str) -> str:
    return library_id if "/" in library_id else f"libraries/{library_id}"


def _library_file_docs_for_library(db: Database, library_id: str) -> list[dict[str, Any]]:
    return cast(
        "list[dict[str, Any]]",
        db.libraries.library_contains_file(_normalize_library_id(library_id), limit=DEFAULT_LIMIT),
    )


def _matches_requested_path(file_doc: dict[str, Any], path: str) -> bool:
    return file_doc.get("normalized_path") == path or file_doc.get("path") == path


def _matches_folder_rel_path(normalized_path: Any, folder_rel_path: str) -> bool:
    if not isinstance(normalized_path, str):
        return False
    if folder_rel_path == "":
        return "/" not in normalized_path
    return normalized_path.startswith(f"{folder_rel_path}/")


def _project_recently_processed_row(file_doc: dict[str, Any]) -> dict[str, Any]:
    scanned_at: int | None = file_doc.get("scanned_at")
    last_tagged_at: int | None = file_doc.get("last_tagged_at")
    candidates: list[tuple[int, str]] = []
    if isinstance(scanned_at, int):
        candidates.append((scanned_at, "scanned"))
    if isinstance(last_tagged_at, int):
        candidates.append((last_tagged_at, "tagged"))
    if candidates:
        activity_at, activity_event = max(candidates, key=lambda t: t[0])
    else:
        activity_at, activity_event = 0, "scanned"
    return {
        "file_id": file_doc.get("_id"),
        "path": file_doc.get("normalized_path"),
        "title": file_doc.get("title"),
        "artist": file_doc.get("artist"),
        "album": file_doc.get("album"),
        "activity_at": activity_at,
        "activity_event": activity_event,
    }


def _sort_key(value: Any) -> tuple[int, Any]:
    if value is None:
        return (1, "")
    if isinstance(value, str):
        return (0, value.casefold())
    return (0, value)


def _library_file_sort_key(file_doc: dict[str, Any]) -> tuple[tuple[int, Any], tuple[int, Any], tuple[int, Any]]:
    return (
        _sort_key(file_doc.get("artist")),
        _sort_key(file_doc.get("album")),
        _sort_key(file_doc.get("title")),
    )


def _project_track_row(file_doc: dict[str, Any]) -> dict[str, Any]:
    path = str(file_doc.get("path") or "")
    return {
        "path": path,
        "title": file_doc.get("title") or Path(path).stem,
        "artist": file_doc.get("artist") or "Unknown Artist",
        "album": file_doc.get("album") or "Unknown Album",
    }


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


def _aggregate_values(collection: Any, field_name: str, *, limit: int | None = None) -> list[Any]:
    aggregate_limit = collection.count() if limit is None else limit
    return [row["value"] for row in collection.aggregate(field_name, limit=aggregate_limit) if "value" in row]


def _get_library_files_by_ids(db: Database, file_ids: list[str]) -> list[dict[str, Any]]:
    if not file_ids:
        return []
    return cast("list[dict[str, Any]]", db.library_files.get.in_(Field("_id", file_ids), limit=None))


def _get_all_library_file_docs(db: Database, limit: int | None = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    file_ids = [
        cast("str", value)
        for value in _aggregate_values(db.library_files, "_id", limit=limit)
        if isinstance(value, str)
    ]
    return _get_library_files_by_ids(db, file_ids)


def _matches_file_filters(file_doc: dict[str, Any], filter_dict: dict[str, Any]) -> bool:
    return all(file_doc.get(field_name) == expected_value for field_name, expected_value in filter_dict.items())


def _matches_text_query(file_doc: dict[str, Any], query_text: str) -> bool:
    lowered_query = query_text.casefold()
    return any(
        lowered_query in field_value.casefold()
        for field_name in ("title", "artist", "album")
        if isinstance((field_value := file_doc.get(field_name)), str)
    )


def _is_numeric_tag_value(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_numeric_target_value(value: float | str) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _project_tag_row(tag_doc: dict[str, Any]) -> dict[str, Any]:
    name_value = tag_doc.get("name")
    tag_value = tag_doc.get("value")
    return {
        "key": name_value,
        "value": tag_value,
        "type": "float" if _is_numeric_tag_value(tag_value) else "string",
        "is_nomarr": isinstance(name_value, str) and name_value.startswith("nom:"),
    }


def _tags_for_file(db: Database, file_id: str) -> list[dict[str, Any]]:
    tag_docs = db.library_files.song_has_tags(file_id, limit=DEFAULT_LIMIT)
    return [
        _project_tag_row(tag_doc) for tag_doc in sorted(tag_docs, key=lambda tag_doc: _sort_key(tag_doc.get("name")))
    ]


def _library_id_for_file(db: Database, file_id: str) -> str | None:
    owning_edges = cast("list[dict[str, Any]]", db.library_contains_file.get(_to=file_id, limit=1))
    return next((library_id for edge in owning_edges if isinstance((library_id := edge.get("_from")), str)), None)


def _hydrate_file_with_tags(db: Database, file_doc: dict[str, Any]) -> dict[str, Any]:
    file_id = file_doc.get("_id")
    if not isinstance(file_id, str):
        return {**file_doc, "tags": [], "library_id": None}
    return {
        **file_doc,
        "tags": _tags_for_file(db, file_id),
        "library_id": _library_id_for_file(db, file_id),
    }


def _paginate_rows(rows: list[dict[str, Any]], limit: int, offset: int) -> list[dict[str, Any]]:
    return rows[offset : offset + limit]


def _collect_file_ids_for_tag_ids(db: Database, tag_ids: set[str]) -> set[str]:
    """Return file ids from a single batch read of `song_has_tags` edges targeting `tag_ids`."""
    edges = cast("list[dict[str, Any]]", db.song_has_tags.get.in_(Field("_to", list(tag_ids))))
    return {edge["_from"] for edge in edges if isinstance(edge.get("_from"), str)}


def get_files_by_ids_with_tags(db: Database, file_ids: list[str]) -> list[dict[str, Any]]:
    """Get files by ids with hydrated tags and owning library id."""
    if not file_ids:
        return []

    file_docs = _get_library_files_by_ids(db, file_ids)
    docs_by_id = {file_id: file_doc for file_doc in file_docs if isinstance((file_id := file_doc.get("_id")), str)}
    return [_hydrate_file_with_tags(db, docs_by_id[file_id]) for file_id in file_ids if file_id in docs_by_id]


def get_library_file(
    db: Database,
    path: str,
    library_id: str | None = None,
) -> dict[str, Any] | None:
    """Get a library-file document by normalized or absolute path."""
    if library_id is not None:
        matching_docs = [
            file_doc
            for file_doc in _library_file_docs_for_library(db, library_id)
            if _matches_requested_path(file_doc, path)
        ]
        if not matching_docs:
            return None
        return min(matching_docs, key=lambda file_doc: str(file_doc.get("_key") or file_doc.get("_id") or ""))

    normalized_matches = cast("list[dict[str, Any]]", db.library_files.get(normalized_path=path, limit=1))
    if normalized_matches:
        return normalized_matches[0]
    return cast("dict[str, Any] | None", db.library_files.get(path=path))


def get_files_by_paths_bulk(db: Database, paths: list[str]) -> dict[str, dict[str, Any]]:
    """Get multiple library-file records keyed by the original input path."""
    if not paths:
        return {}

    path_set = set(paths)
    docs_by_id: dict[str, dict[str, Any]] = {}
    for file_doc in db.library_files.get.in_(Field("path", paths), limit=None):
        file_id = file_doc.get("_id")
        if isinstance(file_id, str):
            docs_by_id[file_id] = file_doc
    for file_doc in db.library_files.get.in_(Field("normalized_path", paths), limit=None):
        file_id = file_doc.get("_id")
        if isinstance(file_id, str):
            docs_by_id[file_id] = file_doc

    result: dict[str, dict[str, Any]] = {}
    for file_doc in docs_by_id.values():
        norm = file_doc.get("normalized_path")
        abs_path = file_doc.get("path")
        if isinstance(norm, str) and norm in path_set and norm not in result:
            result[norm] = file_doc
        if isinstance(abs_path, str) and abs_path in path_set and abs_path not in result:
            result[abs_path] = file_doc
    return result


def detect_nd_path_prefix(db: Database, nd_path: str) -> str | None:
    """Detect the Navidrome prefix that should be stripped from absolute paths."""
    normalized_paths = [
        value for value in _aggregate_values(db.library_files, "normalized_path") if isinstance(value, str) and value
    ]
    best_match = next(
        (
            normalized_path
            for normalized_path in sorted(normalized_paths, key=len, reverse=True)
            if nd_path.endswith(normalized_path)
        ),
        None,
    )
    if best_match is None:
        return None
    return nd_path[: len(nd_path) - len(best_match)]


def list_library_files(
    db: Database,
    limit: int = 100,
    offset: int = 0,
    artist: str | None = None,
    album: str | None = None,
    library_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List library files with optional filters and total count."""
    filter_dict: dict[str, Any] = {}
    if artist:
        filter_dict["artist"] = artist
    if album:
        filter_dict["album"] = album

    if library_id is not None:
        file_docs = [
            file_doc
            for file_doc in _library_file_docs_for_library(db, library_id)
            if _matches_file_filters(file_doc, filter_dict)
        ]
    else:
        file_docs = (
            cast("list[dict[str, Any]]", db.library_files.get(limit=DEFAULT_LIMIT, **filter_dict))
            if filter_dict
            else _get_all_library_file_docs(db, DEFAULT_LIMIT)
        )

    file_docs.sort(key=_library_file_sort_key)
    total = len(file_docs)
    return _paginate_rows(file_docs, limit=limit, offset=offset), total


def get_tagged_file_paths(db: Database) -> list[str]:
    """Return absolute paths for files currently in the tagged state."""
    tagged_file_docs = db.file_states.file_has_state(STATE_TAGGED, limit=DEFAULT_LIMIT)
    file_ids = [file_doc["_id"] for file_doc in tagged_file_docs if isinstance(file_doc.get("_id"), str)]
    if not file_ids:
        return []
    library_file_docs = _get_library_files_by_ids(db, file_ids)
    docs_by_id = {doc["_id"]: doc for doc in library_file_docs if isinstance(doc.get("_id"), str)}
    return [
        str(docs_by_id[file_id]["path"])
        for file_id in file_ids
        if file_id in docs_by_id and isinstance(docs_by_id[file_id].get("path"), str)
    ]


def search_library_files_with_tags(
    db: Database,
    query_text: str = "",
    artist: str | None = None,
    album: str | None = None,
    tag_key: str | None = None,
    tag_value: str | None = None,
    tagged_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Search files with optional tag/text filters and hydrate tags in one query.

    All filtering and pagination is pushed to ArangoDB. Python only hydrates
    the small result page with tags and library_id.

    Args:
        db: Database handle used to search files and hydrate related tags.
        query_text: Free-text substring matched against artist, album, and title with case-insensitive ``LIKE`` filters.
        artist: Case-insensitive exact artist match filter.
        album: Case-insensitive exact album match filter.
        tag_key: When provided alone, filters to files that have any tag with this
            name; when combined with ``tag_value``, filters to files with an exact
            ``(tag_key, tag_value)`` match.
        tag_value: Exact tag value to match; only meaningful when ``tag_key`` is also set.
        tagged_only: When ``True``, restricts results to files in the ``tagged`` state.
        limit: Maximum number of files to return.
        offset: Number of matching files to skip before returning results.

    Returns:
        A tuple of ``(files, total_count)`` where each file dict is a library-file
            document merged with ``tags`` and ``library_id``.
    """
    # candidate_ids: None = universe (no constraint yet); set = narrowed result.
    # Each active filter fetches only matching docs from Arango via the namespace
    # API and intersects into this set. Python only does set math; all I/O is
    # pushed to ArangoDB via the constructed accessor methods.
    #
    # Routing mirrors the frontend prefix syntax:
    #   a:value   → artist LIKE %value%  (artist param)
    #   al:value  → album  LIKE %value%  (album param)
    #   t:value   → title  LIKE %value%  (query_text with artist/album also set)
    #   value     → artist OR album OR title LIKE %value% (query_text alone)
    candidate_ids: set[str] | None = None

    def _intersect(new_ids: set[str]) -> None:
        nonlocal candidate_ids
        candidate_ids = new_ids if candidate_ids is None else candidate_ids & new_ids

    def _ids(docs: list[dict[str, Any]]) -> set[str]:
        return {doc["_id"] for doc in docs if isinstance(doc.get("_id"), str)}

    if artist:
        # a: prefix → substring match in artist field
        _intersect(_ids(db.library_files.get.like("artist", f"%{artist}%")))

    if album:
        # al: prefix → substring match in album field
        _intersect(_ids(db.library_files.get.like("album", f"%{album}%")))

    if query_text:
        q_pattern = f"%{query_text}%"
        if artist or album:
            # t: prefix (query_text alongside a:/al:) → narrow to title only
            _intersect(_ids(db.library_files.get.like("title", q_pattern)))
        else:
            # Unprefixed → OR across all three fields
            matched: set[str] = set()
            for field_name in ("artist", "album", "title"):
                matched |= _ids(db.library_files.get.like(field_name, q_pattern))
            _intersect(matched)

    if tag_key:
        tag_filter: dict[str, Any] = {"name": tag_key}
        if tag_value is not None:
            tag_filter["value"] = tag_value
        matching_tags = cast("list[dict[str, Any]]", db.tags.get(limit=DEFAULT_LIMIT, **tag_filter))
        tag_ids = {tag_id for tag_doc in matching_tags if isinstance((tag_id := tag_doc.get("_id")), str)}
        _intersect(_collect_file_ids_for_tag_ids(db, tag_ids))

    if tagged_only:
        tagged_ids = {
            file_id
            for file_doc in db.file_states.file_has_state(STATE_TAGGED, limit=DEFAULT_LIMIT)
            if isinstance((file_id := file_doc.get("_id")), str)
        }
        _intersect(tagged_ids)

    if candidate_ids is None:
        # No filters active — load all files up to the hard cap.
        file_docs = _get_all_library_file_docs(db, DEFAULT_LIMIT)
    elif not candidate_ids:
        return [], 0
    else:
        file_docs = _get_library_files_by_ids(db, sorted(candidate_ids))

    file_docs.sort(key=_library_file_sort_key)
    total = len(file_docs)
    page_files = _paginate_rows(file_docs, limit=limit, offset=offset)
    return ([_hydrate_file_with_tags(db, file_doc) for file_doc in page_files], total)


def get_recently_processed(
    db: Database,
    limit: int = 20,
    library_id: str | None = None,
) -> list[dict[str, Any]]:
    """Get recently tagged files ordered by most recent activity (``scanned_at`` or ``last_tagged_at``) descending."""
    tagged_file_docs = db.file_states.file_has_state(STATE_TAGGED, limit=DEFAULT_LIMIT)
    if library_id is not None:
        library_file_ids = {
            edge["_to"]
            for edge in cast(
                "list[dict[str, Any]]",
                db.library_contains_file.get(_from=_normalize_library_id(library_id), limit=DEFAULT_LIMIT),
            )
            if isinstance(edge.get("_to"), str)
        }
        tagged_file_docs = [file_doc for file_doc in tagged_file_docs if file_doc.get("_id") in library_file_ids]
    tagged_file_docs.sort(
        key=lambda file_doc: _sort_key(
            max(
                (v for v in (file_doc.get("scanned_at"), file_doc.get("last_tagged_at")) if isinstance(v, int)),
                default=None,
            )
        ),
        reverse=True,
    )
    return [_project_recently_processed_row(file_doc) for file_doc in tagged_file_docs[:limit]]


def get_file_modified_times(db: Database) -> dict[str, int]:
    """Return absolute path to modified-time mapping for all files."""
    file_docs = _get_all_library_file_docs(db, DEFAULT_LIMIT)
    return {
        str(file_doc["path"]): int(file_doc["modified_time"])
        for file_doc in file_docs
        if isinstance(file_doc.get("path"), str) and isinstance(file_doc.get("modified_time"), int)
    }


def get_all_library_paths(db: Database) -> list[str]:
    """Return all absolute library-file paths."""
    return [
        value for value in _aggregate_values(db.library_files, "path", limit=DEFAULT_LIMIT) if isinstance(value, str)
    ]


def list_all_file_ids(db: Database, limit: int | None = None) -> list[str]:
    """Return all library-file ids ordered by ``_key``."""
    collect_limit = limit or DEFAULT_LIMIT
    return [
        value for value in _aggregate_values(db.library_files, "_id", limit=collect_limit) if isinstance(value, str)
    ]


def get_folder_rel_paths(db: Database, library_id: str) -> set[str]:
    """Get cached folder relative paths for one library."""
    return {
        folder_doc["path"]
        for folder_doc in db.libraries.library_contains_folder(_normalize_library_id(library_id), limit=DEFAULT_LIMIT)
        if isinstance(folder_doc.get("path"), str)
    }


def get_files_for_folder(
    db: Database,
    library_id: str,
    folder_rel_path: str,
) -> dict[str, dict[str, Any]]:
    """Get file documents for a single relative folder path."""
    return {
        file_doc["path"]: file_doc
        for file_doc in _library_file_docs_for_library(db, library_id)
        if isinstance(file_doc.get("path"), str)
        and _matches_folder_rel_path(file_doc.get("normalized_path"), folder_rel_path)
    }


def get_files_for_folders(
    db: Database,
    library_id: str,
    folder_rel_paths: list[str],
) -> dict[str, dict[str, Any]]:
    """Batch-fetch file documents for multiple folders."""
    if not folder_rel_paths:
        return {}
    return {
        file_doc["path"]: file_doc
        for file_doc in _library_file_docs_for_library(db, library_id)
        if isinstance(file_doc.get("path"), str)
        and any(
            _matches_folder_rel_path(file_doc.get("normalized_path"), folder_rel_path)
            for folder_rel_path in folder_rel_paths
        )
    }


def count_library_files(db: Database, library_id: str) -> int:
    """Count total files attached to one library via ownership edges."""
    return int(db.library_contains_file.count(Field("_from", _normalize_library_id(library_id))))


def get_library_stats(db: Database, library_id: str | None = None) -> dict[str, Any]:
    """Get aggregate library-file statistics."""
    if library_id is not None:
        file_docs = _library_file_docs_for_library(db, library_id)
        total_files = count_library_files(db, library_id)
    else:
        file_docs = _get_all_library_file_docs(db, None)
        total_files = db.library_files.count()

    result: dict[str, Any] = {
        "total_files": total_files,
        "total_artists": len({file_doc.get("artist") for file_doc in file_docs}),
        "total_albums": len({file_doc.get("album") for file_doc in file_docs}),
        "total_duration": sum(_numeric_value(file_doc.get("duration_seconds")) for file_doc in file_docs),
        "total_size": int(sum(_numeric_value(file_doc.get("file_size")) for file_doc in file_docs)),
    }

    result["needs_tagging_count"] = count_untagged_files(db, library_id)
    return result


def get_library_counts(db: Database) -> dict[str, dict[str, int]]:
    """Get file and folder counts for all libraries."""
    result: dict[str, dict[str, int]] = {}
    library_ids = [
        cast("str", value)
        for value in _aggregate_values(db.library_contains_file, "_from", limit=DEFAULT_LIMIT)
        if isinstance(value, str)
    ]
    for library_id in library_ids:
        edges = cast("list[dict[str, Any]]", db.library_contains_file.get(_from=library_id, limit=DEFAULT_LIMIT))
        file_ids = [edge["_to"] for edge in edges if isinstance(edge.get("_to"), str)]
        file_docs = _get_library_files_by_ids(db, file_ids)
        folder_paths = {parent for file_doc in file_docs if (parent := _path_parent(file_doc.get("path"))) is not None}
        result[library_id] = {
            "file_count": len(file_ids),
            "folder_count": len(folder_paths),
        }
    return result


def get_artist_album_frequencies(db: Database, limit: int) -> dict[str, list[tuple[str, int]]]:
    """Get artist/album frequency rows for analytics views."""
    artist_rows = db.library_files.aggregate("artist", limit=limit)
    album_rows = db.library_files.aggregate("album", limit=limit)
    return {
        "artist_rows": [(value, row["count"]) for row in artist_rows if isinstance((value := row.get("value")), str)],
        "album_rows": [(value, row["count"]) for row in album_rows if isinstance((value := row.get("value")), str)],
    }


def clear_library_data(db: Database) -> None:
    """Nuke all library-file data by truncating every affected collection.

    This is a destructive full-reset.  Rather than paying per-document cascade
    cost, we truncate every collection that holds library-file-derived data in
    one pass.  Order: deepest derived data first, then edges, then documents.
    """
    # Derived data
    for vector_coll in db._template_namespaces.values():  # type: ignore[attr-defined]
        vector_coll.truncate()
    db.segment_scores_stats.truncate()
    # Edge collections
    db.file_has_vectors.truncate()
    db.file_has_segment_stats.truncate()
    db.song_has_tags.truncate()
    db.file_has_state.truncate()
    db.library_contains_file.truncate()
    db.library_contains_folder.truncate()
    db.library_has_scan.truncate()
    db.library_has_pipeline_state.truncate()
    # Documents
    db.tags.truncate()
    db.library_files.truncate()
    db.library_folders.truncate()
    db.library_scans.truncate()
    db.library_pipeline_states.truncate()


def search_files_by_tag(
    db: Database,
    tag_key: str,
    target_value: float | str,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Search files by tag value with numeric-distance or exact-match semantics."""
    if _is_numeric_target_value(target_value):
        numeric_target = float(target_value)
        best_match_by_file_id: dict[str, dict[str, Any]] = {}
        for tag_doc in cast("list[dict[str, Any]]", db.tags.get(name=tag_key, limit=DEFAULT_LIMIT)):
            tag_id = tag_doc.get("_id")
            tag_value = tag_doc.get("value")
            if not isinstance(tag_id, str) or not _is_numeric_tag_value(tag_value):
                continue
            numeric_tag_value = cast("float", tag_value)
            distance = abs(numeric_tag_value - numeric_target)
            for edge in cast("list[dict[str, Any]]", db.song_has_tags.get(_to=tag_id, limit=DEFAULT_LIMIT)):
                file_id = edge.get("_from")
                if not isinstance(file_id, str):
                    continue
                prior_match = best_match_by_file_id.get(file_id)
                if prior_match is None or distance < cast("float", prior_match["distance"]):
                    best_match_by_file_id[file_id] = {
                        "matched_tag": {"key": tag_key, "value": numeric_tag_value},
                        "distance": distance,
                    }

        file_docs = _get_library_files_by_ids(db, list(best_match_by_file_id))
        docs_by_id = {file_id: file_doc for file_doc in file_docs if isinstance((file_id := file_doc.get("_id")), str)}
        sorted_matches = sorted(
            (
                (file_id, docs_by_id[file_id], match_meta)
                for file_id, match_meta in best_match_by_file_id.items()
                if file_id in docs_by_id
            ),
            key=lambda item: (float(item[2]["distance"]), _library_file_sort_key(item[1])),
        )
        paged_matches = sorted_matches[offset : offset + limit]
        results: list[dict[str, Any]] = []
        for _, file_doc, match_meta in paged_matches:
            hydrated_file = _hydrate_file_with_tags(db, file_doc)
            hydrated_file["matched_tag"] = match_meta["matched_tag"]
            hydrated_file["distance"] = match_meta["distance"]
            results.append(hydrated_file)
        return results

    matching_tags = cast(
        "list[dict[str, Any]]",
        db.tags.get(name=tag_key, value=str(target_value), limit=DEFAULT_LIMIT),
    )
    file_ids = _collect_file_ids_for_tag_ids(
        db,
        {tag_id for tag_doc in matching_tags if isinstance((tag_id := tag_doc.get("_id")), str)},
    )
    file_docs = _get_library_files_by_ids(db, list(file_ids))
    file_docs.sort(key=_library_file_sort_key)

    results = []
    for file_doc in _paginate_rows(file_docs, limit=limit, offset=offset):
        hydrated_file = _hydrate_file_with_tags(db, file_doc)
        hydrated_file["matched_tag"] = {"key": tag_key, "value": str(target_value)}
        results.append(hydrated_file)
    return results


def count_files_by_tag(db: Database, tag_key: str, target_value: float | str) -> int:
    """Count files that match a tag-value filter."""
    if _is_numeric_target_value(target_value):
        matching_tag_ids = {
            tag_id
            for tag_doc in cast("list[dict[str, Any]]", db.tags.get(name=tag_key, limit=DEFAULT_LIMIT))
            if isinstance((tag_id := tag_doc.get("_id")), str) and _is_numeric_tag_value(tag_doc.get("value"))
        }
        return len(_collect_file_ids_for_tag_ids(db, matching_tag_ids))

    matching_tag_ids = {
        tag_id
        for tag_doc in cast(
            "list[dict[str, Any]]",
            db.tags.get(name=tag_key, value=str(target_value), limit=DEFAULT_LIMIT),
        )
        if isinstance((tag_id := tag_doc.get("_id")), str)
    }
    return len(_collect_file_ids_for_tag_ids(db, matching_tag_ids))


def get_files_by_chromaprint(
    db: Database,
    chromaprint: str,
    library_id: str | None = None,
) -> list[dict[str, Any]]:
    """Get files whose stored chromaprint matches the supplied value."""
    if library_id is not None:
        return [
            file_doc
            for file_doc in _library_file_docs_for_library(db, library_id)
            if file_doc.get("chromaprint") == chromaprint
        ]

    return cast("list[dict[str, Any]]", db.library_files.get.many(chromaprint=chromaprint, limit=None))


def get_tracks_by_file_ids(
    db: Database,
    file_ids: set[str],
    order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch track metadata for the supplied file ids."""
    if not file_ids:
        return []

    file_docs = _get_library_files_by_ids(db, list(file_ids))
    if order_by:
        for column, direction in reversed(order_by):
            file_docs.sort(key=lambda file_doc: _sort_key(file_doc.get(column)), reverse=direction == "desc")
    else:
        random.shuffle(file_docs)
    if limit is not None:
        file_docs = file_docs[:limit]
    return [_project_track_row(file_doc) for file_doc in file_docs]


def get_tracks_for_matching(db: Database, library_id: str | None = None) -> list[dict[str, Any]]:
    """Get track rows for fuzzy playlist matching, optionally scoped to a library."""
    if library_id:
        file_docs = [
            file_doc for file_doc in _library_file_docs_for_library(db, library_id) if file_doc.get("is_valid") is True
        ]
    else:
        file_docs = cast("list[dict[str, Any]]", db.library_files.get(is_valid=True, limit=DEFAULT_LIMIT))

    file_ids = [file_id for file_doc in file_docs if isinstance(file_id := file_doc.get("_id"), str)]
    isrc_rows = db.library_files.song_has_tags.by_ids(file_ids, name="isrc") if file_ids else []
    isrc_by_file = {
        row["start_id"]: tag_doc.get("value")
        for row in isrc_rows
        if isinstance(row.get("start_id"), str) and isinstance(tag_doc := row.get("v"), dict)
    }

    results: list[dict[str, Any]] = []
    for file_doc in file_docs:
        file_id = file_doc.get("_id")
        if not isinstance(file_id, str):
            continue
        results.append(
            {
                "_id": file_id,
                "path": file_doc.get("path"),
                "title": file_doc.get("title"),
                "artist": file_doc.get("artist"),
                "album": file_doc.get("album"),
                "isrc": isrc_by_file.get(file_id),
            }
        )
    return results
