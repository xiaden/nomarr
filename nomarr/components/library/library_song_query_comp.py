"""Library song query helpers.

Multi-hop reads routed through the intent-level persistence facades.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from nomarr.components.library.library_song_state_comp import count_untagged_files
from nomarr.components.library.tag_hydration_comp import hydrate_songs_with_metadata
from nomarr.components.library.tag_mapping_comp import file_tag_from_tag_row, is_numeric_tag_value
from nomarr.helpers.constants.file_states import STATE_PROCESSED
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_dataclass import SongTagMatch
    from nomarr.helpers.dto.library_dto import FileTag
    from nomarr.persistence.db import Database

DEFAULT_LIMIT = 1000


def get_song_by_id(db: Database, song_id: int) -> dict[str, Any] | None:
    """Get one library-song document by ``song_id``."""
    song = db.library.get_song(song_id)
    return song.to_dict() if song is not None else None


def count_recently_tagged(db: Database, window_seconds: int = 300) -> int:
    """Count songs tagged within the recent window (default 5 minutes)."""
    cutoff_ms = now_ms().value - window_seconds * 1000
    return db.library.count_recently_tagged(cutoff_ms)


def get_existing_file_paths(db: Database, library: Library, paths: list[str]) -> set[str]:
    """Return paths that already exist in the target library's songs table."""
    if not paths:
        return set()
    return set(db.library.list_existing_song_paths(library, paths))


def _normalize_path(path: str) -> str:
    """Normalize a caller path for the song identity lookup."""
    return Path(path).as_posix().lstrip("./")


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
        "file_id": file_doc.get("id"),
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


def _library_song_sort_key(file_doc: dict[str, Any]) -> tuple[tuple[int, Any], tuple[int, Any], tuple[int, Any]]:
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


def _get_songs_by_ids(db: Database, song_ids: list[int]) -> list[dict[str, Any]]:
    if not song_ids:
        return []
    return [song.to_dict() for song in db.library.list_songs_by_ids(song_ids)]


def _get_all_library_songs(db: Database, limit: int | None = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Return songs across all libraries, optionally capped after aggregation.

    The intent-level facade has no global ``list_songs`` (song listing requires a
    ``library_id``), so the full listing is assembled by iterating the
    known libraries and collecting every song before applying the global cap.
    """
    songs: list[dict[str, Any]] = []
    for library in db.library.list_libraries():
        songs.extend(song.to_dict() for song in db.library.list_songs(library, limit=None))
    if limit is not None:
        songs = songs[:limit]
    return songs


def _hydrate_files_with_tagged_state(db: Database, file_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate song docs with ``has_tagged_state`` derived from the processed state membership."""
    song_ids = [song_id for file_doc in file_docs if isinstance((song_id := file_doc.get("id")), int)]
    if not song_ids:
        return list(file_docs)

    tagged_song_ids = set(db.app.song_ids_with_state(STATE_PROCESSED, limit=None))

    return [
        {**file_doc, "has_tagged_state": song_id in tagged_song_ids}
        if isinstance((song_id := file_doc.get("id")), int)
        else dict(file_doc)
        for file_doc in file_docs
    ]


def _matches_file_filters(file_doc: dict[str, Any], filter_dict: dict[str, Any]) -> bool:
    return all(file_doc.get(field_name) == expected_value for field_name, expected_value in filter_dict.items())


def _is_numeric_target_value(value: float | str) -> bool:
    """Whether a curated tag target value is numeric (int/float, non-bool)."""
    return is_numeric_tag_value(value)


def _tags_for_song(db: Database, song_id: int) -> list[FileTag]:
    song_identity = db.library.resolve_song_identity(song_id)
    if song_identity is None:
        return []
    assignments = db.library.list_tags_for_song(song_identity)
    return [
        file_tag_from_tag_row({"name": assignment.name, "value": assignment.value, "namespace": assignment.namespace})
        for assignment in sorted(assignments, key=lambda assignment: _sort_key(assignment.name))
    ]


def _tags_by_name(db: Database, name: str) -> list[TagRef]:
    return list(db.library.list_tags(name=name, limit=None))


def _tags_by_name_value(db: Database, name: str, value: str) -> list[TagRef]:
    return [identity for identity in _tags_by_name(db, name) if identity.value == value]


def _library_id_from_file_doc(file_doc: dict[str, Any]) -> int | None:
    library_id = file_doc.get("library_id")
    return library_id if isinstance(library_id, int) else None


def _hydrate_files_with_tags(db: Database, file_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hydrate many song docs with tags and owning library ids in batched lookups."""
    song_ids = [song_id for file_doc in file_docs if isinstance(song_id := file_doc.get("id"), int)]
    if not song_ids:
        return [{**file_doc, "tags": [], "library_id": None} for file_doc in file_docs]

    identity_map = db.library.resolve_song_identities(song_ids)
    if not identity_map:
        return [{**file_doc, "tags": [], "library_id": None} for file_doc in file_docs]

    id_to_identity = {identity: song_id for song_id, identity in identity_map.items()}
    raw_tags_by_identity = db.library.list_song_tags_for_songs(list(identity_map.values()))
    tags_by_file = {
        song_id: sorted(
            [
                file_tag_from_tag_row(
                    {"name": assignment.name, "value": assignment.value, "namespace": assignment.namespace}
                )
                for assignment in assignments
            ],
            key=lambda tag_row: _sort_key(tag_row.key),
        )
        for identity, assignments in raw_tags_by_identity.items()
        if (song_id := id_to_identity.get(identity)) is not None
    }

    library_ids_by_file = db.library.get_library_ids_for_songs(song_ids)

    return [
        {
            **file_doc,
            "tags": tags_by_file.get(song_id, []),
            "library_id": library_ids_by_file.get(song_id),
        }
        if isinstance((song_id := file_doc.get("id")), int)
        else {**file_doc, "tags": [], "library_id": None}
        for file_doc in file_docs
    ]


def _hydrate_file_with_tags(db: Database, file_doc: dict[str, Any]) -> dict[str, Any]:
    song_id = file_doc.get("id")
    if not isinstance(song_id, int):
        return {**file_doc, "tags": [], "library_id": None}
    hydrated = _hydrate_files_with_tags(db, [file_doc])
    return hydrated[0]


def _paginate_rows(rows: list[dict[str, Any]], limit: int, offset: int) -> list[dict[str, Any]]:
    return rows[offset : offset + limit]


def get_songs_by_ids_with_tags(db: Database, song_ids: list[int]) -> list[dict[str, Any]]:
    """Get songs by ids with hydrated tags and owning library id."""
    if not song_ids:
        return []

    file_docs = _get_songs_by_ids(db, song_ids)
    docs_by_id = {song_id: file_doc for file_doc in file_docs if isinstance((song_id := file_doc.get("id")), int)}
    ordered_docs = [docs_by_id[song_id] for song_id in song_ids if song_id in docs_by_id]
    return _hydrate_files_with_tags(db, ordered_docs)


def get_library_song(
    db: Database,
    path: str,
    library: Library | None = None,
) -> dict[str, Any] | None:
    """Get a library-song document by normalized or absolute path.

    Scoped lookups use the canonical normalized-path identity in the facade.
    """
    if library is not None:
        normalized_path = _normalize_path(path)
        song = db.library.get_song_by_normalized_path(normalized_path, library)
        return song.to_dict() if song is not None else None

    song = db.library.find_song_by_path_any_library(path)
    return song.to_dict() if song is not None else None


def require_library_song_id(
    db: Database,
    path: str,
    library: Library | None = None,
) -> int:
    """Return the library-song ``id`` for a path or raise ``FileNotFoundError``."""
    library_file = get_library_song(db, path, library=library)
    if not library_file:
        msg = f"File not in library: {path}"
        raise FileNotFoundError(msg)
    return library_file["id"]  # type: ignore[no-any-return]


def get_songs_by_paths_bulk(db: Database, paths: list[str]) -> dict[str, dict[str, Any]]:
    """Get multiple library-song records keyed by the original input path."""
    if not paths:
        return {}

    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        file_doc = get_library_song(db, path)
        if file_doc is not None:
            result[path] = file_doc
    return result


def detect_nd_path_prefix(db: Database, nd_path: str) -> str | None:
    """Detect the Navidrome prefix that should be stripped from absolute paths."""
    normalized_paths: list[str] = []
    normalized_paths.extend(
        str(file_doc["normalized_path"])
        for library in db.library.list_libraries()
        for file_doc in (song.to_dict() for song in db.library.list_songs(library, limit=DEFAULT_LIMIT))
        if isinstance(file_doc.get("normalized_path"), str) and file_doc.get("normalized_path")
    )
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


def list_songs(
    db: Database,
    limit: int = 100,
    offset: int = 0,
    artist: str | None = None,
    album: str | None = None,
    library: Library | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List library songs with optional filters; returns (rows, total_count)."""
    if library is not None:
        file_docs = [song.to_dict() for song in db.library.list_songs(library, limit=None)]
    else:
        # Collect the complete global result before filtering and pagination.
        # Applying the helper's default cap here drops songs before an offset
        # can be applied, making pages after the first 1,000 rows incorrect.
        file_docs = _get_all_library_songs(db, limit=None)

    file_docs = hydrate_songs_with_metadata(db, file_docs)

    filter_dict: dict[str, Any] = {}
    if artist:
        filter_dict["artist"] = artist
    if album:
        filter_dict["album"] = album
    if filter_dict:
        file_docs = [doc for doc in file_docs if _matches_file_filters(doc, filter_dict)]

    file_docs.sort(key=_library_song_sort_key)
    total = len(file_docs)
    return _paginate_rows(file_docs, limit=limit, offset=offset), total


def get_tagged_file_paths(db: Database) -> list[str]:
    """Return absolute paths for songs currently in the processed state."""
    tagged_songs = db.app.songs_with_state(STATE_PROCESSED, limit=DEFAULT_LIMIT)
    return [song.path for song in tagged_songs if isinstance(song.path, str)]


def search_songs_with_tags(
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
    """Search songs with tag/text filters; returns (songs, total_count).

    All filtering is pushed to PostgreSQL via set-intersection of candidate ids.
    """
    # candidate_ids: None = universe (no constraint yet); set = narrowed result.
    # Each active filter fetches only matching rows from PostgreSQL via the namespace
    # API and intersects into this set. Python only does set math; all I/O is
    # pushed to PostgreSQL via the constructed accessor methods.
    #
    # Routing mirrors the frontend prefix syntax:
    #   a:value   → artist LIKE %value%  (artist param)
    #   al:value  → album  LIKE %value%  (album param)
    #   t:value   → title  LIKE %value%  (query_text with artist/album also set)
    #   value     → artist OR album OR title LIKE %value% (query_text alone)
    candidate_ids: set[int] | None = None

    def _intersect(new_ids: set[int]) -> None:
        nonlocal candidate_ids
        candidate_ids = new_ids if candidate_ids is None else candidate_ids & new_ids

    if artist:
        # a: prefix → substring match in artist tag
        _intersect({song.song_id for song in db.library.find_songs_with_tag_pattern("artist", f"%{artist}%")})

    if album:
        # al: prefix → substring match in album tag
        _intersect({song.song_id for song in db.library.find_songs_with_tag_pattern("album", f"%{album}%")})

    if query_text:
        q_pattern = f"%{query_text}%"
        if artist or album:
            # t: prefix (query_text alongside a:/al:) → narrow to title only
            _intersect({song.song_id for song in db.library.find_songs_with_tag_pattern("title", q_pattern)})
        else:
            # Unprefixed → OR across title (tag) and artist/album (tags)
            matched: set[int] = set()
            matched |= {song.song_id for song in db.library.find_songs_with_tag_pattern("title", q_pattern)}
            for tag_name in ("artist", "album"):
                matched |= {song.song_id for song in db.library.find_songs_with_tag_pattern(tag_name, q_pattern)}
            _intersect(matched)

    if tag_key:
        matching_tags = (
            _tags_by_name_value(db, tag_key, str(tag_value)) if tag_value is not None else _tags_by_name(db, tag_key)
        )
        tag_matched: set[int] = set()
        for identity in matching_tags:
            for song in db.library.find_songs_with_tag(identity, limit=None):
                tag_matched.add(song.song_id)
        _intersect(tag_matched)

    if tagged_only:
        tagged_ids = set(db.app.song_ids_with_state(STATE_PROCESSED, limit=DEFAULT_LIMIT))
        _intersect(tagged_ids)

    if candidate_ids is None:
        # No filters active — load all songs up to the hard cap.
        file_docs = _get_all_library_songs(db, DEFAULT_LIMIT)
    elif not candidate_ids:
        return [], 0
    else:
        file_docs = _get_songs_by_ids(db, sorted(candidate_ids))

    file_docs = hydrate_songs_with_metadata(db, file_docs)
    file_docs.sort(key=_library_song_sort_key)
    total = len(file_docs)
    page_files = _paginate_rows(file_docs, limit=limit, offset=offset)
    return (_hydrate_files_with_tags(db, page_files), total)


def get_recently_processed(
    db: Database,
    limit: int = 20,
    library: Library | None = None,
) -> list[dict[str, Any]]:
    """Return recently processed songs ordered by activity descending.

    The query is capped at 1,000 rows; we do not support more than 1k recent
    processed songs in one update.

    Scoping is by the natural ``Library`` identity (mechanism A); the backing
    activity query no longer accepts an int library filter, so a library scope
    is applied by filtering against the library's song-id set.
    """
    # overlap: mechanism-A natural-name threading (P4-S8) - sibling song-plan
    # files are under concurrent edit; preserve adjacent hunks.
    query_kwargs: dict[str, Any] = {
        "limit": DEFAULT_LIMIT,
        "order_by_activity": True,
    }
    tagged_file_docs: list[dict[str, Any]] = [
        song.to_dict() for song in db.app.songs_with_state(STATE_PROCESSED, **query_kwargs)
    ]
    if library is not None:
        library_song_ids = {song.song_id for song in db.library.list_songs(library, limit=None)}
        tagged_file_docs = [doc for doc in tagged_file_docs if doc.get("id") in library_song_ids]
    tagged_file_docs = hydrate_songs_with_metadata(db, tagged_file_docs)
    return [_project_recently_processed_row(file_doc) for file_doc in tagged_file_docs[:limit]]


def get_song_modified_times(db: Database) -> dict[str, int]:
    """Return absolute path to modified-time mapping for all files."""
    file_docs = _get_all_library_songs(db, DEFAULT_LIMIT)
    return {
        str(file_doc["path"]): int(file_doc["modified_time"])
        for file_doc in file_docs
        if isinstance(file_doc.get("path"), str) and isinstance(file_doc.get("modified_time"), int)
    }


def get_all_library_paths(db: Database) -> list[str]:
    """Return all absolute library-file paths."""
    paths: list[str] = []
    paths.extend(
        str(file_doc["path"])
        for library in db.library.list_libraries()
        for file_doc in (song.to_dict() for song in db.library.list_songs(library, limit=DEFAULT_LIMIT))
        if isinstance(file_doc.get("path"), str)
    )
    return paths


def get_sample_normalized_path(db: Database) -> str | None:
    """Return one normalized_path from the library for diagnostic purposes."""
    for library in db.library.list_libraries():
        file_docs = [song.to_dict() for song in db.library.list_songs(library, limit=1)]
        for file_doc in file_docs:
            if isinstance(file_doc.get("normalized_path"), str) and file_doc.get("normalized_path"):
                return str(file_doc["normalized_path"])
    return None


def list_all_song_ids(db: Database, limit: int | None = None) -> list[int]:
    """Return all library song ids."""
    collect_limit = limit or DEFAULT_LIMIT
    song_ids: list[int] = []
    for library in db.library.list_libraries():
        song_ids.extend(db.library.list_library_song_ids(library, limit=collect_limit))
    return song_ids


def get_folder_rel_paths(db: Database, library: Library) -> set[str]:
    """Get cached folder relative paths for one library."""
    return {folder.path for folder in db.library.list_folders_for_library(library) if isinstance(folder.path, str)}


def get_songs_for_folder(
    db: Database,
    library: Library,
    folder_rel_path: str,
) -> dict[str, dict[str, Any]]:
    """Get song documents for a single folder."""
    file_docs = [song.to_dict() for song in db.library.list_songs_for_folder(library, folder_rel_path)]
    return {file_doc["path"]: file_doc for file_doc in file_docs if isinstance(file_doc.get("path"), str)}


def get_songs_for_folders(
    db: Database,
    library: Library,
    folder_rel_paths: list[str],
) -> dict[str, dict[str, Any]]:
    """Batch-fetch song documents for multiple folders.

    TODO(migrate): fetches all files for the library then filters by
    normalized_path prefix in Python. Persistence needs a multi-folder SQL
    query so this doesn't load the entire library into memory.
    """
    if not folder_rel_paths:
        return {}
    file_docs = _hydrate_files_with_tagged_state(
        db,
        [song.to_dict() for song in db.library.list_songs(library, limit=None)],
    )
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
    library: Library,
    chromaprint: str,
) -> dict[str, Any] | None:
    """Return the library file matching ``chromaprint``, or ``None``. Used for DB-lookup move detection."""
    song = db.library.find_library_song_by_chromaprint(library, chromaprint)
    return song.to_dict() if song is not None else None


def get_library_stats(db: Database, library: Library | None = None) -> dict[str, Any]:
    """Get aggregate library-song statistics (songs, artists, albums, duration, size)."""
    if library is not None:
        file_docs = [song.to_dict() for song in db.library.list_songs(library, limit=None)]
        total_files = db.library.count_songs_for_library(library)
        song_ids = [doc["id"] for doc in file_docs if isinstance(doc.get("id"), int)]
        identity_map = db.library.resolve_song_identities(song_ids) if song_ids else {}
        artist_values: set[Any] = set()
        album_values: set[Any] = set()
        if identity_map:
            tags_by_identity = db.library.list_song_tags_for_songs(list(identity_map.values()))
            for assignments in tags_by_identity.values():
                artist_values.update(assignment.value for assignment in assignments if assignment.name == "artist")
                album_values.update(assignment.value for assignment in assignments if assignment.name == "album")
        total_artists = len(artist_values)
        total_albums = len(album_values)
    else:
        file_docs = _get_all_library_songs(db, None)
        total_files = len(file_docs)
        total_artists = len(_tags_by_name(db, "artist"))
        total_albums = len(_tags_by_name(db, "album"))

    result: dict[str, Any] = {
        "total_files": total_files,
        "total_artists": total_artists,
        "total_albums": total_albums,
        "total_duration": sum(_numeric_value(file_doc.get("duration_seconds")) for file_doc in file_docs),
        "total_size": int(sum(_numeric_value(file_doc.get("file_size")) for file_doc in file_docs)),
    }

    result["needs_tagging_count"] = count_untagged_files(db, library)
    return result


def get_library_counts(db: Database) -> dict[str, dict[str, int]]:
    """Return song and folder counts for all libraries, keyed by library name.

    Overlap note (P2-S4): the library facade no longer exposes
    ``list_library_keys`` / generated library ids, so the counts are keyed by
    the library's natural ``name``. ``list_songs`` accepts the ``Library`` key
    directly (P3-S5), so no generated id is needed here.
    """
    result: dict[str, dict[str, int]] = {}
    for library in db.library.list_libraries():
        # P3 song-facade handoff resolved: ``list_songs`` now accepts the
        # natural ``Library`` key, so the per-library listing needs no id.
        file_docs = [song.to_dict() for song in db.library.list_songs(library, limit=None)]
        folder_paths = {parent for file_doc in file_docs if (parent := _path_parent(file_doc.get("path"))) is not None}
        result[library.name] = {
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
    """Perform a destructive full reset, including each library's pipeline state."""
    # Derived data
    from nomarr.components.ml.inference.ml_output_stream_store_comp import delete_output_streams

    for collection_name in db.ml.list_vector_collection_names():
        db.ml.clear_vector_collection(collection_name)
    for library in db.library.list_libraries():
        for song_id in db.library.list_library_song_ids(library, limit=None):
            delete_output_streams(db, song_id)
        db.library.remove_pipeline_state(library)
    # Link/junction tables
    db.library.truncate_song_tag_assignments()
    db.app.truncate_song_state_edges()
    db.library.truncate_song_links()
    db.library.truncate_folder_links()
    # Core tables
    db.library.truncate_tags()
    db.library.truncate_songs()
    db.library.truncate_folders()
    db.library.truncate_scan_records()


def _numeric_match_to_file_doc(match: SongTagMatch) -> dict[str, Any]:
    """Project a domain tag match for downstream response enrichment."""
    return match.song.to_dict()


def search_songs_by_tag(
    db: Database,
    tag_key: str,
    target_value: float | str,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Search songs by tag value with numeric-distance or exact-match semantics."""
    if _is_numeric_target_value(target_value):
        # Numeric search is SQL-paginated (ADR-045: artist/album/title are
        # tag-derived, not song columns, so the complete-result metadata sort no
        # longer applies). PostgreSQL selects one closest numeric tag per song,
        # orders by ``distance ASC`` then unique ``song id ASC`` (per-tag
        # tie-break by tag id), and applies offset/limit before any rows reach
        # Python. Only the SQL-returned page is hydrated.
        numeric_target = float(target_value)
        identity = TagRef(name=tag_key, value=numeric_target)
        rows = db.library.find_songs_with_numeric_tag(identity, limit=limit, offset=offset)
        if not rows:
            return []
        file_docs = [_numeric_match_to_file_doc(match) for match in rows]
        file_docs = hydrate_songs_with_metadata(db, file_docs)
        hydrated_files = _hydrate_files_with_tags(db, file_docs)
        results: list[dict[str, Any]] = []
        for hydrated_file, match in zip(hydrated_files, rows, strict=False):
            # Row's ``matched_tag`` is the matched tag's string value; convert to
            # float to keep the exact public shape (old numeric branch emitted a
            # float ``value``).
            hydrated_file["matched_tag"] = {"key": tag_key, "value": float(match.matched_tag)}
            hydrated_file["distance"] = match.distance
            results.append(hydrated_file)
        return results

    identity = TagRef(name=tag_key, value=str(target_value))
    file_docs = [song.to_dict() for song in db.library.find_songs_with_tag(identity, limit=None)]
    file_docs = hydrate_songs_with_metadata(db, file_docs)
    file_docs.sort(key=_library_song_sort_key)

    results = []
    hydrated_page = _hydrate_files_with_tags(db, _paginate_rows(file_docs, limit=limit, offset=offset))
    for hydrated_file in hydrated_page:
        hydrated_file["matched_tag"] = {"key": tag_key, "value": str(target_value)}
        results.append(hydrated_file)
    return results


def count_songs_by_tag(db: Database, tag_key: str, target_value: float | str) -> int:
    """Count songs matching a tag-value filter."""
    if _is_numeric_target_value(target_value):
        # Numeric count is a separate uncapped ``COUNT(DISTINCT song_id)`` SQL
        # intent sharing the numeric search predicate (ADR-045); it must agree
        # with the searchable result universe even beyond the legacy 1000-edge
        # cap, so it never materializes tags/edges in Python.
        return db.library.count_songs_by_numeric_tag(tag_key, float(target_value))

    return db.library.count_songs_by_tag(tag_key, str(target_value))


def get_songs_by_chromaprint(
    db: Database,
    chromaprint: str,
    library: Library | None = None,
) -> list[dict[str, Any]]:
    """Return files matching a chromaprint fingerprint."""
    if library is not None:
        return [
            file_doc
            for file_doc in (song.to_dict() for song in db.library.list_songs(library, limit=None))
            if file_doc.get("chromaprint") == chromaprint
        ]

    matches: list[dict[str, Any]] = []
    for library in db.library.list_libraries():
        match = db.library.find_library_song_by_chromaprint(library, chromaprint)
        if match is not None:
            matches.append(match.to_dict())
    return matches


def get_tracks_by_song_ids(
    db: Database,
    song_ids: set[int],
    order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch track metadata for the supplied song ids."""
    if not song_ids:
        return []

    file_docs = _get_songs_by_ids(db, list(song_ids))
    file_docs = hydrate_songs_with_metadata(db, file_docs)
    if order_by:
        for column, direction in reversed(order_by):
            file_docs.sort(key=lambda file_doc: _sort_key(file_doc.get(column)), reverse=direction == "desc")
    else:
        random.shuffle(file_docs)
    if limit is not None:
        file_docs = file_docs[:limit]
    return [_project_track_row(file_doc) for file_doc in file_docs]


def get_tracks_for_matching(db: Database, library: Library | None = None) -> list[dict[str, Any]]:
    """Get track rows for fuzzy playlist matching, optionally scoped to a library."""
    if library is not None:
        file_docs = [song.to_dict() for song in db.library.list_tracks_for_matching(library, limit=DEFAULT_LIMIT)]
    else:
        file_docs = [
            file_doc
            for lib in db.library.list_libraries()
            for file_doc in (song.to_dict() for song in db.library.list_tracks_for_matching(lib, limit=DEFAULT_LIMIT))
        ]

    file_docs = hydrate_songs_with_metadata(db, file_docs)

    song_ids = [song_id for file_doc in file_docs if isinstance(song_id := file_doc.get("id"), int)]
    identity_map = db.library.resolve_song_identities(song_ids) if song_ids else {}
    id_to_identity = {identity: song_id for song_id, identity in identity_map.items()}
    tags_by_identity = db.library.list_song_tags_for_songs(list(identity_map.values())) if identity_map else {}
    isrc_by_file = {
        song_id: next(
            (assignment.value for assignment in assignments if assignment.name == "isrc"),
            None,
        )
        for identity, assignments in tags_by_identity.items()
        if (song_id := id_to_identity.get(identity)) is not None
    }

    results: list[dict[str, Any]] = []
    for file_doc in file_docs:
        song_id = file_doc.get("id")
        if not isinstance(song_id, int):
            continue
        results.append(
            {
                "id": song_id,
                "path": file_doc.get("path"),
                "title": file_doc.get("title"),
                "artist": file_doc.get("artist"),
                "album": file_doc.get("album"),
                "isrc": isrc_by_file.get(song_id),
            }
        )
    return results
