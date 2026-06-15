"""Tag-enrichment query helpers for library-file documents.

These helpers own tag-lookup, tag-hydration, and tag-search logic that was
previously co-located with core file queries.  Extracted during the Phase 4
oversized-file-split to keep ``library_file_query_comp`` under the 500-line
threshold.
"""

from __future__ import annotations

from typing import Any, cast

from nomarr.components.library.tag_hydration_comp import hydrate_songs_with_metadata
from nomarr.persistence.db import Database

# ---------------------------------------------------------------------------
# Small helpers also defined (identically) in library_file_query_comp —
# duplicated intentionally to avoid a circular dependency between the two
# modules.
# ---------------------------------------------------------------------------


def _sort_key(value: Any) -> tuple[int, Any]:
    if value is None:
        return (1, "")
    if isinstance(value, str):
        return (0, value.casefold())
    return (0, value)


def _paginate_rows(rows: list[dict[str, Any]], limit: int, offset: int) -> list[dict[str, Any]]:
    return rows[offset : offset + limit]


# ---------------------------------------------------------------------------
# Tag value predicates
# ---------------------------------------------------------------------------


def _is_numeric_tag_value(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_numeric_target_value(value: float | str) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Tag document projection
# ---------------------------------------------------------------------------


def _project_tag_row(tag_doc: dict[str, Any]) -> dict[str, Any]:
    name_value = tag_doc.get("name")
    tag_value = tag_doc.get("value")
    return {
        "key": name_value,
        "value": tag_value,
        "type": "float" if _is_numeric_tag_value(tag_value) else "string",
        "is_nomarr": isinstance(name_value, str) and name_value.startswith("nom:"),
    }


# ---------------------------------------------------------------------------
# Single-collection tag lookups
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# File → tag hydration
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Tag → file-ID resolution
# ---------------------------------------------------------------------------


def _collect_file_ids_for_tag_ids(db: Database, tag_ids: set[str]) -> set[str]:
    """Return file ids matched by the supplied tag ids via song-tag edges."""
    edges = cast("list[dict[str, Any]]", db.library.get_song_tag_edges_for_tags(list(tag_ids)))
    return {edge["_from"] for edge in edges if isinstance(edge.get("_from"), str)}


# ---------------------------------------------------------------------------
# Public API — get files with tag hydration
# ---------------------------------------------------------------------------


def get_files_by_ids_with_tags(db: Database, file_ids: list[str]) -> list[dict[str, Any]]:
    """Get files by ids with hydrated tags and owning library id."""
    if not file_ids:
        return []

    file_docs = cast("list[dict[str, Any]]", db.library.list_files_by_ids(file_ids))
    docs_by_id = {file_id: file_doc for file_doc in file_docs if isinstance((file_id := file_doc.get("_id")), str)}
    ordered_docs = [docs_by_id[file_id] for file_id in file_ids if file_id in docs_by_id]
    return _hydrate_files_with_tags(db, ordered_docs)


# ---------------------------------------------------------------------------
# Tag-based search
# ---------------------------------------------------------------------------


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
            db.library.get_song_tag_edges_for_tags(list(tag_value_by_id.keys()), limit=1000),
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
        file_docs_list = hydrate_songs_with_metadata(db, file_docs_list)
        file_docs_by_id = {
            file_id: file_doc for file_doc in file_docs_list if isinstance((file_id := file_doc.get("_id")), str)
        }

        sorted_matches = sorted(
            (
                (file_id, match_meta)
                for file_id, match_meta in best_match_by_file_id.items()
                if file_id in file_docs_by_id
            ),
            key=lambda item: (float(item[1]["distance"]), _sort_key(file_docs_by_id[item[0]])),
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
    file_docs = hydrate_songs_with_metadata(db, file_docs)
    file_docs.sort(key=_sort_key)

    results = []
    for hydrated_file in _hydrate_files_with_tags(db, _paginate_rows(file_docs, limit=limit, offset=offset)):
        hydrated_file["matched_tag"] = {"key": tag_key, "value": str(target_value)}
        results.append(hydrated_file)
    return results


def count_files_by_tag(db: Database, tag_key: str, target_value: float | str) -> int:
    """Count files that match a tag-value filter.

    TODO(migrate): loads all tags for tag_key then traverses song-tag edges in
    Python. db.library.count_files_by_tag(tag_key, target_value) already exists
    for the string case but doesn't handle numeric proximity. Extend that method
    to accept an optional numeric mode so this can be removed.
    """
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
