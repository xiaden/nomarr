"""Library-file query helpers extracted from legacy persistence mixins.

These helpers own the complex multi-hop reads that now route through the
intent-level `db.library`, `db.app`, and `db.ml` persistence sub-facades.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Literal, cast

from nomarr.components.library.library_file_state_comp import count_untagged_files
from nomarr.components.library.library_id_comp import normalize_library_id
from nomarr.helpers.constants.file_states import STATE_TAGGED
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.db import Database

DEFAULT_LIMIT = 1000


def get_file_by_id(db: Database, file_id: str) -> dict[str, Any] | None:
    """Get one library-file document by ``_id``."""
    return cast("dict[str, Any] | None", db.library.get_file(file_id))


def count_recently_tagged(db: Database, window_seconds: int = 300) -> int:
    """Count files whose ``last_tagged_at`` timestamp falls within the recent window.

    Args:
        db: Database instance.
        window_seconds: How far back to look (default 5 minutes).

    Returns:
        Number of files tagged within the window.

    """
    cutoff_ms = now_ms().value - window_seconds * 1000
    return db.library.count_recently_tagged(cutoff_ms)


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
    return set(db.library.list_existing_file_paths(paths))


def _library_file_docs_for_library(db: Database, library_id: str) -> list[dict[str, Any]]:
    return cast(
        "list[dict[str, Any]]",
        db.library.list_library_files(normalize_library_id(library_id), limit=None),
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


def _get_library_files_by_ids(db: Database, file_ids: list[str]) -> list[dict[str, Any]]:
    if not file_ids:
        return []
    return cast("list[dict[str, Any]]", db.library.list_files_by_ids(file_ids))


def _get_all_library_file_docs(db: Database, limit: int | None = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", db.library.list_files(limit=limit))


def _hydrate_files_with_tagged_state(db: Database, file_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate file docs with ``has_tagged_state`` derived from ``file_has_state`` edges."""
    file_ids = [file_id for file_doc in file_docs if isinstance((file_id := file_doc.get("_id")), str)]
    if not file_ids:
        return list(file_docs)

    tagged_file_ids = set(db.app.list_files_in_state(STATE_TAGGED, limit=None))

    return [
        {**file_doc, "has_tagged_state": file_id in tagged_file_ids}
        if isinstance((file_id := file_doc.get("_id")), str)
        else dict(file_doc)
        for file_doc in file_docs
    ]


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
    tag_docs = db.library.list_tags_for_file(file_id)
    return [
        _project_tag_row(tag_doc) for tag_doc in sorted(tag_docs, key=lambda tag_doc: _sort_key(tag_doc.get("name")))
    ]


def _tags_by_name(db: Database, name: str) -> list[dict[str, Any]]:
    total_tags = db.library.count_tags()
    if total_tags <= 0:
        return []
    return cast("list[dict[str, Any]]", db.library.list_tags_by_name(name, limit=total_tags))


def _tags_by_name_value(db: Database, name: str, value: str) -> list[dict[str, Any]]:
    return [tag_doc for tag_doc in _tags_by_name(db, name) if tag_doc.get("value") == value]


def _library_id_from_file_doc(file_doc: dict[str, Any]) -> str | None:
    library_key = file_doc.get("library_key")
    return normalize_library_id(library_key) if isinstance(library_key, str) else None


def _hydrate_files_with_tags(db: Database, file_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hydrate many file docs with tags and owning library ids in batched lookups."""
    file_ids = [file_id for file_doc in file_docs if isinstance(file_id := file_doc.get("_id"), str)]
    if not file_ids:
        return [{**file_doc, "tags": [], "library_id": None} for file_doc in file_docs]

    raw_tags_by_file = db.library.list_file_tags_for_files(file_ids)
    tags_by_file = {
        file_id: sorted(
            [_project_tag_row(tag_doc) for tag_doc in tag_docs],
            key=lambda tag_row: _sort_key(tag_row.get("key")),
        )
        for file_id, tag_docs in raw_tags_by_file.items()
    }

    library_ids_by_file = db.library.get_library_ids_for_files(file_ids)

    return [
        {
            **file_doc,
            "tags": tags_by_file.get(file_id, []),
            "library_id": library_ids_by_file.get(file_id),
        }
        if isinstance((file_id := file_doc.get("_id")), str)
        else {**file_doc, "tags": [], "library_id": None}
        for file_doc in file_docs
    ]


def _hydrate_file_with_tags(db: Database, file_doc: dict[str, Any]) -> dict[str, Any]:
    file_id = file_doc.get("_id")
    if not isinstance(file_id, str):
        return {**file_doc, "tags": [], "library_id": None}
    return _hydrate_files_with_tags(db, [file_doc])[0]


def _paginate_rows(rows: list[dict[str, Any]], limit: int, offset: int) -> list[dict[str, Any]]:
    return rows[offset : offset + limit]


def _collect_file_ids_for_tag_ids(db: Database, tag_ids: set[str]) -> set[str]:
    """Return file ids matched by the supplied tag ids via song-tag edges."""
    edges = cast("list[dict[str, Any]]", db.library.get_song_tag_edges_for_tags(list(tag_ids)))
    return {edge["_from"] for edge in edges if isinstance(edge.get("_from"), str)}


def get_files_by_ids_with_tags(db: Database, file_ids: list[str]) -> list[dict[str, Any]]:
    """Get files by ids with hydrated tags and owning library id."""
    if not file_ids:
        return []

    file_docs = _get_library_files_by_ids(db, file_ids)
    docs_by_id = {file_id: file_doc for file_doc in file_docs if isinstance((file_id := file_doc.get("_id")), str)}
    ordered_docs = [docs_by_id[file_id] for file_id in file_ids if file_id in docs_by_id]
    return _hydrate_files_with_tags(db, ordered_docs)


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

    normalized_matches = cast(
        "list[dict[str, Any]]",
        db.library.list_files(filters={"normalized_path": path}, limit=1),
    )
    if normalized_matches:
        return normalized_matches[0]
    return cast("dict[str, Any] | None", db.library.find_file_by_path_any_library(path))


def require_library_file_id(
    db: Database,
    path: str,
    library_id: str | None = None,
) -> str:
    """Return the library-file ``_id`` for a path or raise ``FileNotFoundError``."""
    library_file = get_library_file(db, path, library_id=library_id)
    if not library_file:
        msg = f"File not in library: {path}"
        raise FileNotFoundError(msg)
    return str(library_file["_id"])


def get_files_by_paths_bulk(db: Database, paths: list[str]) -> dict[str, dict[str, Any]]:
    """Get multiple library-file records keyed by the original input path."""
    if not paths:
        return {}

    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        file_doc = get_library_file(db, path)
        if file_doc is not None:
            result[path] = file_doc
    return result


def detect_nd_path_prefix(db: Database, nd_path: str) -> str | None:
    """Detect the Navidrome prefix that should be stripped from absolute paths."""
    normalized_paths = [
        str(file_doc["normalized_path"])
        for file_doc in db.library.list_files(limit=DEFAULT_LIMIT)
        if isinstance(file_doc.get("normalized_path"), str) and file_doc.get("normalized_path")
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
            cast("list[dict[str, Any]]", db.library.list_files(filters=filter_dict, limit=DEFAULT_LIMIT))
            if filter_dict
            else _get_all_library_file_docs(db, DEFAULT_LIMIT)
        )

    file_docs.sort(key=_library_file_sort_key)
    total = len(file_docs)
    return _paginate_rows(file_docs, limit=limit, offset=offset), total


def get_tagged_file_paths(db: Database) -> list[str]:
    """Return absolute paths for files currently in the tagged state."""
    tagged_file_docs = db.app.list_file_docs_in_state(STATE_TAGGED, limit=DEFAULT_LIMIT)
    return [str(file_doc["path"]) for file_doc in tagged_file_docs if isinstance(file_doc.get("path"), str)]


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
        # a: prefix → substring match in artist tag
        _intersect(_ids(db.library.search_files_by_tag_pattern("artist", f"%{artist}%", limit=None)))

    if album:
        # al: prefix → substring match in album tag
        _intersect(_ids(db.library.search_files_by_tag_pattern("album", f"%{album}%", limit=None)))

    if query_text:
        q_pattern = f"%{query_text}%"
        if artist or album:
            # t: prefix (query_text alongside a:/al:) → narrow to title only
            _intersect(_ids(db.library.search_files_by_text("title", q_pattern, limit=None)))
        else:
            # Unprefixed → OR across title (document field) and artist/album (tags)
            matched: set[str] = set()
            matched |= _ids(db.library.search_files_by_text("title", q_pattern, limit=None))
            for tag_name in ("artist", "album"):
                matched |= _ids(db.library.search_files_by_tag_pattern(tag_name, q_pattern, limit=None))
            _intersect(matched)

    if tag_key:
        matching_tags = (
            _tags_by_name_value(db, tag_key, str(tag_value)) if tag_value is not None else _tags_by_name(db, tag_key)
        )
        tag_ids = {tag_id for tag_doc in matching_tags if isinstance((tag_id := tag_doc.get("_id")), str)}
        _intersect(_collect_file_ids_for_tag_ids(db, tag_ids))

    if tagged_only:
        tagged_ids = set(db.app.list_files_in_state(STATE_TAGGED, limit=DEFAULT_LIMIT))
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
    return (_hydrate_files_with_tags(db, page_files), total)


def get_recently_processed(
    db: Database,
    limit: int = 20,
    library_id: str | None = None,
) -> list[dict[str, Any]]:
    """Get recently tagged files ordered by most recent activity (``scanned_at`` or ``last_tagged_at``) descending."""
    tagged_file_docs = db.app.list_file_docs_in_state(STATE_TAGGED, limit=DEFAULT_LIMIT)
    if library_id is not None:
        library_file_ids = set(db.library.list_library_file_ids(normalize_library_id(library_id), limit=DEFAULT_LIMIT))
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
        str(file_doc["path"])
        for file_doc in db.library.list_files(limit=DEFAULT_LIMIT)
        if isinstance(file_doc.get("path"), str)
    ]


def get_sample_normalized_path(db: Database) -> str | None:
    """Return one normalized_path from the library for diagnostic purposes."""
    values = [
        str(file_doc["normalized_path"])
        for file_doc in db.library.list_files(limit=1)
        if isinstance(file_doc.get("normalized_path"), str) and file_doc.get("normalized_path")
    ]
    return values[0] if values else None


def list_all_file_ids(db: Database, limit: int | None = None) -> list[str]:
    """Return all library-file ids ordered by ``_key``."""
    collect_limit = limit or DEFAULT_LIMIT
    return [
        str(file_doc["_id"])
        for file_doc in db.library.list_files(limit=collect_limit)
        if isinstance(file_doc.get("_id"), str)
    ]


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
    """Get file documents for a single folder. Has_tagged_state is annotated in-query."""
    file_docs = db.library.list_library_files_for_folder(normalize_library_id(library_id), folder_rel_path)
    return {file_doc["path"]: file_doc for file_doc in file_docs if isinstance(file_doc.get("path"), str)}


def get_files_for_folders(
    db: Database,
    library_id: str,
    folder_rel_paths: list[str],
) -> dict[str, dict[str, Any]]:
    """Batch-fetch file documents for multiple folders."""
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


def count_library_files(db: Database, library_id: str) -> int:
    """Count total files attached to one library via ownership edges."""
    return db.library.count_library_file_links(normalize_library_id(library_id))


def get_library_stats(db: Database, library_id: str | None = None) -> dict[str, Any]:
    """Get aggregate library-file statistics."""
    if library_id is not None:
        file_docs = _library_file_docs_for_library(db, library_id)
        total_files = count_library_files(db, library_id)
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
    """Get file and folder counts for all libraries."""
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
    # Note: pipeline state *vertices* (library_pipeline_states/idle, scanning, etc.)
    # are singleton schema documents seeded at startup — do NOT truncate them.
    # Only the edges linking libraries to those vertices need clearing.


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
        total = db.library.count_tags()
        all_tag_docs = cast("list[dict[str, Any]]", db.library.list_tags_by_name(tag_key, limit=total))
        tag_value_by_id = {
            tag_id: cast("float", tag_value)
            for tag_doc in all_tag_docs
            if isinstance((tag_id := tag_doc.get("_id")), str)
            and _is_numeric_tag_value(tag_value := tag_doc.get("value"))
        }
        if not tag_value_by_id:
            return []

        edges = cast(
            "list[dict[str, Any]]",
            db.library.get_song_tag_edges_for_tags(list(tag_value_by_id.keys()), limit=DEFAULT_LIMIT),
        )
        best_match_by_file_id: dict[str, dict[str, Any]] = {}
        for edge in edges:
            file_id = edge.get("_from")
            tag_id = edge.get("_to")
            if not isinstance(file_id, str) or not isinstance(tag_id, str):
                continue
            tag_value = tag_value_by_id.get(tag_id)
            if tag_value is None:
                continue
            distance = abs(tag_value - numeric_target)
            prior_match = best_match_by_file_id.get(file_id)
            if prior_match is None or distance < cast("float", prior_match["distance"]):
                best_match_by_file_id[file_id] = {
                    "matched_tag": {"key": tag_key, "value": tag_value},
                    "distance": distance,
                }

        all_file_ids = list(best_match_by_file_id.keys())
        file_docs_list = cast("list[dict[str, Any]]", db.library.list_files_by_ids(all_file_ids))
        file_docs_by_id = {
            file_id: file_doc for file_doc in file_docs_list if isinstance((file_id := file_doc.get("_id")), str)
        }

        sorted_matches = sorted(
            (
                (file_id, match_meta)
                for file_id, match_meta in best_match_by_file_id.items()
                if file_id in file_docs_by_id
            ),
            key=lambda item: (float(item[1]["distance"]), _library_file_sort_key(file_docs_by_id[item[0]])),
        )
        paged_matches = sorted_matches[offset : offset + limit]
        paged_file_docs = [file_docs_by_id[file_id] for file_id, _ in paged_matches]
        hydrated_files = _hydrate_files_with_tags(db, paged_file_docs)
        results: list[dict[str, Any]] = []
        for hydrated_file, (_, match_meta) in zip(hydrated_files, paged_matches, strict=False):
            hydrated_file["matched_tag"] = match_meta["matched_tag"]
            hydrated_file["distance"] = match_meta["distance"]
            results.append(hydrated_file)
        return results

    file_docs = cast(
        "list[dict[str, Any]]",
        db.library.search_files_by_tag(tag_key, str(target_value), limit=None),
    )
    file_docs.sort(key=_library_file_sort_key)

    results = []
    for hydrated_file in _hydrate_files_with_tags(db, _paginate_rows(file_docs, limit=limit, offset=offset)):
        hydrated_file["matched_tag"] = {"key": tag_key, "value": str(target_value)}
        results.append(hydrated_file)
    return results


def count_files_by_tag(db: Database, tag_key: str, target_value: float | str) -> int:
    """Count files that match a tag-value filter."""
    total = db.library.count_tags()
    tag_docs = cast("list[dict[str, Any]]", db.library.list_tags_by_name(tag_key, limit=total))

    if _is_numeric_target_value(target_value):
        tag_ids = [
            tag_id
            for tag_doc in tag_docs
            if isinstance((tag_id := tag_doc.get("_id")), str) and _is_numeric_tag_value(tag_doc.get("value"))
        ]
    else:
        tag_ids = [tag_id for tag_doc in tag_docs if isinstance((tag_id := tag_doc.get("_id")), str)]

    if not tag_ids:
        return 0

    edges = cast("list[dict[str, Any]]", db.library.get_song_tag_edges_for_tags(tag_ids))
    return len({edge["_from"] for edge in edges if isinstance(edge.get("_from"), str)})


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

    return cast(
        "list[dict[str, Any]]",
        db.library.list_files(filters={"chromaprint": chromaprint}, limit=None),
    )


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
        file_docs = cast(
            "list[dict[str, Any]]",
            db.library.list_tracks_for_matching(library_id, limit=DEFAULT_LIMIT),
        )
    else:
        file_docs = cast("list[dict[str, Any]]", db.library.list_files(filters={"is_valid": True}, limit=DEFAULT_LIMIT))

    file_ids = [file_id for file_doc in file_docs if isinstance(file_id := file_doc.get("_id"), str)]
    isrc_by_file = {
        file_id: next(
            (tag_doc.get("value") for tag_doc in tag_docs if tag_doc.get("name") == "isrc"),
            None,
        )
        for file_id, tag_docs in db.library.list_file_tags_for_files(file_ids).items()
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
