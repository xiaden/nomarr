"""Tag query helpers extracted from legacy tag persistence."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.tag_curation_dto import TagSongItem
from nomarr.helpers.dto.tags_dto import Tags, TagValue

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _narrow_tag_list(result: object) -> list[dict[str, Any]]:
    """Runtime type-narrowing for DB query results expected to be tag lists."""
    if isinstance(result, list):
        return result
    return []


def _narrow_tag_dict_opt(result: object) -> dict[str, Any] | None:
    """Runtime type-narrowing for DB query results expected to be optional tag dicts."""
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    return None


def _numeric_value(value: object) -> float | None:
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


def _matches_tag_operator(tag_value: object, operator: str, value: TagValue) -> bool:
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


def _first_name_value(tag_docs: list[dict[str, Any]], name: str) -> str:
    """Return the first string value for a tag name, or an empty string."""
    for tag in tag_docs:
        if tag.get("name") != name:
            continue
        value = tag.get("value")
        if isinstance(value, str):
            return value
    return ""


async def get_tag(db: Database, tag_id: int) -> dict[str, Any] | None:
    """Get one tag document by ``id``."""
    return _narrow_tag_dict_opt(await db.library.get_tag(tag_id))


async def count_songs_for_tag(db: Database, tag_id: int) -> int:
    """Count files linked to one tag using the intent-level library facade."""
    tag = await get_tag(db, tag_id)
    if tag is None:
        return 0
    return len(await db.library.list_file_ids_for_tag_id(tag_id, limit=None))


async def list_tags_by_name(
    db: Database,
    name: str | None = None,
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
    sort_by_count: bool = False,
) -> list[dict[str, Any]]:
    """List tag values, optionally filtered by tag name and search text."""
    if sort_by_count:
        # For sort_by_count we need all matching tags sorted by count desc — fetch all, then sort.
        # This is an uncommon path so the cost is acceptable.
        total = await db.library.count_tags_filtered(name=name, search=search)
        raw_tags = _narrow_tag_list(
            await db.library.list_tags_with_song_count(name=name, search=search, limit=total, offset=0),
        )
        raw_tags.sort(key=lambda item: (-item.get("song_count", 0), str(item.get("value", "")).lower()))
        return raw_tags[offset : offset + limit]

    # Default path: sort by value, paginated server-side
    return _narrow_tag_list(
        await db.library.list_tags_with_song_count(name=name, search=search, limit=limit, offset=offset),
    )


async def count_tags_by_name(db: Database, name: str | None = None, search: str | None = None) -> int:
    """Count tags, optionally filtered by tag name and search text."""
    return await db.library.count_tags_filtered(name=name, search=search)


async def get_song_tags(db: Database, song_id: int, name: str | None = None, nomarr_only: bool = False) -> Tags:
    """Return tags for one song as a ``Tags`` DTO."""
    tag_docs = _narrow_tag_list(await db.library.list_tags_for_file(song_id))
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


async def get_nomarr_tags_bulk(db: Database, file_ids: list[int]) -> dict[int, Tags]:
    """Return Nomarr-prefixed tags for many files in one query."""
    if not file_ids:
        return {}

    result_raw = await db.library.list_file_tags_for_files(
        file_ids,
        name_starts_with="nom:",
    )
    if not isinstance(result_raw, dict):
        return {}
    tags_by_file = {
        int(k): list(v) if isinstance(v, list) else [] for k, v in result_raw.items() if isinstance(k, int)
    }
    result: dict[int, Tags] = {}
    for file_id, tag_docs in tags_by_file.items():
        rows = [
            {"name": tag_name, "value": tag["value"]}
            for tag in tag_docs
            if isinstance(tag_name := tag.get("name"), str) and "value" in tag
        ]
        if rows:
            result[file_id] = Tags.from_db_rows(rows)
    return result


async def list_songs_for_tag(db: Database, tag_id: int, limit: int = 100, offset: int = 0) -> list[int]:
    """List song ids connected to one tag via the intent-level library facade."""
    tag = await get_tag(db, tag_id)
    if tag is None:
        return []
    result = await db.library.list_file_ids_for_tag_id(tag_id, limit=limit, offset=offset)
    if isinstance(result, list):
        return [fid for fid in result if isinstance(fid, int)]
    return []


async def get_file_ids_matching_tag(db: Database, name: str, operator: str, value: TagValue) -> set[int]:
    """Return file ids matching one tag comparison."""
    total = await db.library.count_tags()
    if total <= 0:
        return set()

    all_tags = _narrow_tag_list(
        await db.library.list_tags(name=name, limit=total)
        if name is not None
        else await db.library.list_tags(limit=total)
    )
    matching_tags = [tag for tag in all_tags if _matches_tag_operator(tag.get("value"), operator, value)]

    file_ids: set[int] = set()
    for tag in matching_tags:
        tag_name = tag.get("name")
        tag_value = tag.get("value")
        if not isinstance(tag_name, str) or tag_value is None:
            continue
        for file_doc in _narrow_tag_list(
            await db.library.search_files_by_tag(tag_name, str(tag_value), limit=None),
        ):
            file_id = file_doc.get("id")
            if isinstance(file_id, int):
                file_ids.add(file_id)
    return file_ids


async def get_file_ids_for_tags(
    db: Database,
    tag_specs: list[tuple[str, str]],
    library_id: int | None = None,
) -> dict[tuple[str, str], set[int]]:
    """Get file-id sets for many ``(name, value)`` tag specs."""
    result: dict[tuple[str, str], set[int]] = {}

    # Resolve library-scoped file ids when a library is provided
    library_ids: set[int] | None = None
    if library_id is not None:
        library_ids = {
            file_id
            for file_doc in _narrow_tag_list(await db.library.list_library_files(library_id))
            if isinstance(file_id := file_doc.get("id"), int)
        }

    total = await db.library.count_tags()

    for name, value in tag_specs:
        if value == "*":
            tags: list[dict[str, Any]] = (
                _narrow_tag_list(await db.library.list_tags(name=name, limit=total)) if total > 0 else []
            )
        else:
            tags = []
            seen_ids: set[int] = set()
            for candidate in _candidate_filter_values(value):
                for tag in _narrow_tag_list(
                    await db.library.list_tags(name=name, value=candidate, limit=total),
                ):
                    tag_id = tag.get("id")
                    if not isinstance(tag_id, int) or tag_id in seen_ids:
                        continue
                    seen_ids.add(tag_id)
                    tags.append(tag)

        file_ids: set[int] = set()
        for tag in tags:
            tag_name = tag.get("name")
            tag_value = tag.get("value")
            if not isinstance(tag_name, str) or tag_value is None:
                continue
            for file_doc in _narrow_tag_list(
                await db.library.search_files_by_tag(tag_name, str(tag_value), limit=None),
            ):
                file_id = file_doc.get("id")
                if isinstance(file_id, int):
                    file_ids.add(file_id)

        if library_ids is not None:
            file_ids &= library_ids
        result[(name, value)] = file_ids

    return result


async def get_file_ids_for_mood_tags(
    db: Database,
    mood_values: list[str],
    mood_tier: str = "mood-strict",
    library_id: int | None = None,
) -> dict[str, set[int]]:
    """Return file-id sets for mood values using CONTAINS array matching."""
    result: dict[str, set[int]] = {}
    name = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier

    # Resolve library-scoped file ids when a library is provided
    library_ids: set[int] | None = None
    if library_id is not None:
        library_ids = {
            file_id
            for file_doc in _narrow_tag_list(await db.library.list_library_files(library_id))
            if isinstance(file_id := file_doc.get("id"), int)
        }

    for mood_value in mood_values:
        file_docs = _narrow_tag_list(
            await db.library.search_files_by_tag_contains(name, mood_value, limit=None),
        )
        file_ids: set[int] = {file_id for file_doc in file_docs if isinstance((file_id := file_doc.get("id")), int)}
        if library_ids is not None:
            file_ids &= library_ids
        result[mood_value] = file_ids

    return result


async def get_unique_mood_values(db: Database, mood_tier: str = "mood-strict", limit: int = 100) -> list[str]:
    """Return unique mood values for one tier."""
    name = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier
    tags = await list_tags_by_name(db, name=name, limit=limit, offset=0)
    values = sorted({str(tag["value"]) for tag in tags})
    return values[:limit]


async def get_distinct_tag_values_for_files(db: Database, file_ids: list[int], name: str) -> list[str]:
    """Return distinct values for one tag name across many files."""
    if not file_ids:
        return []

    raw = await db.library.list_file_tags_for_files(file_ids)
    if not isinstance(raw, dict):
        return []
    tags_by_file = {
        k: list(v) if isinstance(v, list) else [] for k, v in raw.items() if isinstance(k, int)
    }
    values = {
        value
        for tag_docs in tags_by_file.values()
        for tag in tag_docs
        if tag.get("name") == name and isinstance(value := tag.get("value"), str)
    }
    return sorted(values)


async def get_tag_values_grouped_by_file(db: Database, file_ids: list[int], name: str) -> dict[int, set[str]]:
    """Return tag values grouped by file for one tag name."""
    if not file_ids:
        return {}

    raw = await db.library.list_file_tags_for_files(file_ids)
    if not isinstance(raw, dict):
        return {}
    tags_by_file = {
        k: list(v) if isinstance(v, list) else [] for k, v in raw.items() if isinstance(k, int)
    }
    result: dict[int, set[str]] = {}
    for file_id, tag_docs in tags_by_file.items():
        for tag in tag_docs:
            if tag.get("name") != name:
                continue
            value = tag.get("value")
            if not isinstance(value, str):
                continue
            result.setdefault(file_id, set()).add(value)
    return result


async def get_tag_songs_with_metadata(db: Database, tag_id: int, limit: int = 50, offset: int = 0) -> list[TagSongItem]:
    """Return song rows for a tag with basic file metadata."""
    result: list[TagSongItem] = []
    for file_id in await list_songs_for_tag(db, tag_id, limit=limit, offset=offset):
        file_doc = _narrow_tag_dict_opt(await db.library.get_file(file_id))
        if file_doc is None:
            continue
        tag_docs = _narrow_tag_list(await db.library.list_tags_for_file(file_id))
        result.append(
            TagSongItem(
                file_id=str(file_id),
                title=_first_name_value(tag_docs, "title"),
                artist=_first_name_value(tag_docs, "artist"),
                album=_first_name_value(tag_docs, "album"),
                path=str(file_doc.get("path", "")),
            ),
        )
    return result
