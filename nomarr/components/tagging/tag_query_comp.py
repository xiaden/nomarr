"""Tag query helpers extracted from legacy tag persistence."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.tags_dto import Tags, TagValue

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _all_tags(db: Database) -> list[dict[str, Any]]:
    """Return all tag documents with explicit pagination."""
    total = db.tags.count()
    if total <= 0:
        return []

    page_size = min(total, 1000)
    tags: list[dict[str, Any]] = []
    current_offset = 0
    while current_offset < total:
        page = db.tags.get.many.by_filter({}, limit=page_size, offset=current_offset)
        if not page:
            break
        tags.extend(page)
        current_offset += len(page)
    return tags


def _tags_for_name(db: Database, name: str | None) -> list[dict[str, Any]]:
    """Return tags for one tag name or all tags when name is omitted."""
    if name is None:
        return _all_tags(db)

    total = db.tags.count()
    if total <= 0:
        return []
    return db.tags.name.get.many(name, limit=total)


def _filter_tags_by_search(tags: list[dict[str, Any]], search: str | None) -> list[dict[str, Any]]:
    """Apply case-insensitive substring filtering on tag values."""
    if search is None:
        return tags

    search_lower = search.lower()
    return [tag for tag in tags if search_lower in str(tag.get("value", "")).lower()]


def _enrich_tag(tag: dict[str, Any], song_count: int) -> dict[str, Any]:
    """Return the public tag payload with computed song count."""
    return {
        "_id": tag.get("_id"),
        "_key": tag.get("_key"),
        "name": tag.get("name"),
        "value": tag.get("value"),
        "song_count": song_count,
    }


def _numeric_value(value: Any) -> float | None:
    """Convert values to numeric form when possible for ordered comparisons."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _matches_tag_operator(tag_value: Any, operator: str, value: TagValue) -> bool:
    """Evaluate a supported tag comparison in Python."""
    if operator in {"==", "="}:
        return bool(tag_value == value)
    if operator == "!=":
        return bool(tag_value != value)
    if operator == "CONTAINS":
        return str(value).lower() in str(tag_value).lower()
    if operator == "NOTCONTAINS":
        return str(value).lower() not in str(tag_value).lower()

    left_num = _numeric_value(tag_value)
    right_num = _numeric_value(value)
    if left_num is not None and right_num is not None:
        if operator == ">":
            return left_num > right_num
        if operator == "<":
            return left_num < right_num
        if operator == ">=":
            return left_num >= right_num
        if operator == "<=":
            return left_num <= right_num
        return bool(tag_value == value)

    left_cmp = str(tag_value)
    right_cmp = str(value)
    if operator == ">":
        return left_cmp > right_cmp
    if operator == "<":
        return left_cmp < right_cmp
    if operator == ">=":
        return left_cmp >= right_cmp
    if operator == "<=":
        return left_cmp <= right_cmp
    return bool(tag_value == value)


def _file_ids_for_tag_docs(db: Database, tags: list[dict[str, Any]]) -> set[str]:
    """Traverse from tags to linked file ids and return the union set."""
    edges = db.song_has_tags._to.get.in_(
        [tag["_id"] for tag in tags if isinstance(tag.get("_id"), str)],
        limit=None,
    )
    return {edge["_from"] for edge in edges if isinstance(edge.get("_from"), str)}


def _library_file_ids(db: Database, library_id: str | None) -> set[str] | None:
    """Return the scoped file-id set for a library when one is provided."""
    if library_id is None:
        return None

    return {
        file_id
        for file_doc in db.libraries.traversal(library_id, "library_contains_file")
        if isinstance(file_id := file_doc.get("_id"), str)
    }


def _candidate_filter_values(value: str) -> list[TagValue]:
    """Generate exact-match candidates including numeric coercions."""
    candidates: list[TagValue] = [value]
    with contextlib.suppress(ValueError):
        candidates.append(int(value))
    try:
        float_value = float(value)
    except ValueError:
        return candidates
    if float_value not in candidates:
        candidates.append(float_value)
    return candidates


def _exact_tags_for_name_value(db: Database, name: str, value: str) -> list[dict[str, Any]]:
    """Return tags matching one name/value pair, including numeric coercions."""
    tags: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for candidate in _candidate_filter_values(value):
        for tag in db.tags.get.many.by_filter({"name": name, "value": candidate}, limit=db.tags.count()):
            tag_id = tag.get("_id")
            if not isinstance(tag_id, str) or tag_id in seen_ids:
                continue
            seen_ids.add(tag_id)
            tags.append(tag)
    return tags


def _first_name_value(tag_docs: list[dict[str, Any]], name: str) -> str:
    """Return the first string value for a tag name, or an empty string."""
    for tag in tag_docs:
        if tag.get("name") != name:
            continue
        value = tag.get("value")
        if isinstance(value, str):
            return value
    return ""


def get_tag(db: Database, tag_id: str) -> dict[str, Any] | None:
    """Get one tag document by ``_id``."""
    return db.tags.get(tag_id)


def list_tags_by_name(
    db: Database,
    name: str | None = None,
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
    sort_by_count: bool = False,
) -> list[dict[str, Any]]:
    """List tag values, optionally filtered by tag name and search text."""
    matched_tags = _filter_tags_by_search(_tags_for_name(db, name), search)
    count_by_tag_id = {row["value"]: row["count"] for row in db.song_has_tags._to.aggregate()}

    if sort_by_count:
        counted_tags = [
            (tag, count_by_tag_id.get(str(tag["_id"]), 0)) for tag in matched_tags if isinstance(tag.get("_id"), str)
        ]
        counted_tags.sort(key=lambda item: (-item[1], str(item[0].get("value", "")).lower()))
        return [_enrich_tag(tag, song_count) for tag, song_count in counted_tags[offset : offset + limit]]

    matched_tags.sort(key=lambda tag: str(tag.get("value", "")).lower())
    page = matched_tags[offset : offset + limit]
    return [
        _enrich_tag(tag, count_by_tag_id.get(tag_id, 0)) for tag in page if isinstance(tag_id := tag.get("_id"), str)
    ]


def count_tags_by_name(db: Database, name: str | None = None, search: str | None = None) -> int:
    """Count tags, optionally filtered by tag name and search text."""
    return len(_filter_tags_by_search(_tags_for_name(db, name), search))


def get_song_tags(db: Database, song_id: str, name: str | None = None, nomarr_only: bool = False) -> Tags:
    """Return tags for one song as a ``Tags`` DTO."""
    tag_docs = db.library_files.traversal(song_id, "song_has_tags")
    rows: list[dict[str, Any]] = []
    for tag in tag_docs:
        tag_name = tag.get("name")
        if not isinstance(tag_name, str) or "value" not in tag:
            continue
        if name is not None and tag_name != name:
            continue
        if nomarr_only and not tag_name.startswith("nom:"):
            continue
        rows.append({"name": tag_name, "value": tag["value"]})
    return Tags.from_db_rows(rows)


def get_nomarr_tags_bulk(db: Database, file_ids: list[str]) -> dict[str, Tags]:
    """Return Nomarr-prefixed tags for many files in one query."""
    if not file_ids:
        return {}

    rows = db.library_files.traversal.by_ids(
        list(file_ids),
        "song_has_tags",
        target_like_starts_with=("name", "nom:"),
    )
    rows_by_file: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        start_id = row.get("start_id")
        tag = row.get("v")
        if not isinstance(start_id, str) or not isinstance(tag, dict):
            continue
        tag_name = tag.get("name")
        if not isinstance(tag_name, str) or "value" not in tag:
            continue
        rows_by_file.setdefault(start_id, []).append({"name": tag_name, "value": tag["value"]})
    return {file_id: Tags.from_db_rows(rows) for file_id, rows in rows_by_file.items()}


def list_songs_for_tag(db: Database, tag_id: str, limit: int = 100, offset: int = 0) -> list[str]:
    """List song ids connected to one tag."""
    edges = db.song_has_tags._to.get.many(tag_id, limit=limit, offset=offset)
    return [str(edge["_from"]) for edge in edges if edge.get("_from")]


def get_file_ids_matching_tag(db: Database, name: str, operator: str, value: TagValue) -> set[str]:
    """Return file ids matching one tag comparison."""
    matching_tags = [
        tag for tag in _tags_for_name(db, name) if _matches_tag_operator(tag.get("value"), operator, value)
    ]
    return _file_ids_for_tag_docs(db, matching_tags)


def get_file_ids_for_tags(
    db: Database,
    tag_specs: list[tuple[str, str]],
    library_id: str | None = None,
) -> dict[tuple[str, str], set[str]]:
    """Get file-id sets for many ``(name, value)`` tag specs."""
    result: dict[tuple[str, str], set[str]] = {}
    library_ids = _library_file_ids(db, library_id)

    for name, value in tag_specs:
        if value == "*":
            tags = _tags_for_name(db, name)
        else:
            tags = _exact_tags_for_name_value(db, name, value)

        file_ids = _file_ids_for_tag_docs(db, tags)
        if library_ids is not None:
            file_ids &= library_ids
        result[(name, value)] = file_ids

    return result


def get_file_ids_for_mood_tags(
    db: Database,
    mood_values: list[str],
    mood_tier: str = "mood-strict",
    library_id: str | None = None,
) -> dict[str, set[str]]:
    """Get file-id sets for many mood values within one mood tier."""
    result: dict[str, set[str]] = {}
    name = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier
    library_ids = _library_file_ids(db, library_id)

    for mood_value in mood_values:
        file_ids = _file_ids_for_tag_docs(db, _exact_tags_for_name_value(db, name, mood_value))
        if library_ids is not None:
            file_ids &= library_ids
        result[mood_value] = file_ids

    return result


def get_unique_mood_values(db: Database, mood_tier: str = "mood-strict", limit: int = 100) -> list[str]:
    """Return unique mood values for one tier."""
    name = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier
    tags = list_tags_by_name(db, name=name, limit=limit, offset=0)
    values = sorted({str(tag["value"]) for tag in tags})
    return values[:limit]


def get_distinct_tag_values_for_files(db: Database, file_ids: list[str], name: str) -> list[str]:
    """Return distinct values for one tag name across many files."""
    if not file_ids:
        return []

    rows = db.library_files.traversal.by_ids(
        list(file_ids),
        "song_has_tags",
        target_filter={"name": name},
    )
    values = {
        value for row in rows if isinstance(tag := row.get("v"), dict) and isinstance(value := tag.get("value"), str)
    }
    return sorted(values)


def get_tag_values_grouped_by_file(db: Database, file_ids: list[str], name: str) -> dict[str, set[str]]:
    """Return tag values grouped by file for one tag name."""
    if not file_ids:
        return {}

    rows = db.library_files.traversal.by_ids(
        list(file_ids),
        "song_has_tags",
        target_filter={"name": name},
    )
    result: dict[str, set[str]] = {}
    for row in rows:
        start_id = row.get("start_id")
        tag = row.get("v")
        if not isinstance(start_id, str) or not isinstance(tag, dict):
            continue
        value = tag.get("value")
        if not isinstance(value, str):
            continue
        result.setdefault(start_id, set()).add(value)
    return result


def get_tag_songs_with_metadata(db: Database, tag_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Return song rows for a tag with basic file metadata."""
    result: list[dict[str, Any]] = []
    for file_doc in db.tags.traversal(tag_id, "song_has_tags", limit=limit, offset=offset):
        file_id = file_doc.get("_id")
        if not isinstance(file_id, str):
            continue
        tag_docs = db.library_files.traversal(file_id, "song_has_tags")
        result.append(
            {
                "file_id": file_id,
                "title": str(file_doc.get("title", "")),
                "artist": _first_name_value(tag_docs, "artist"),
                "album": _first_name_value(tag_docs, "album"),
                "path": str(file_doc.get("path", "")),
            },
        )
    return result
