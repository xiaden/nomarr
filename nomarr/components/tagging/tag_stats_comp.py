"""Tag statistics helpers built on the intent-level library persistence facade."""

from __future__ import annotations

from collections import defaultdict
from math import floor
from typing import TYPE_CHECKING, Any

from nomarr.components.tagging.tag_query_comp import (
    _narrow_tag_list,
    get_tag,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


async def _all_library_files(db: Database) -> list[dict[str, Any]]:
    """Return all library file documents with explicit pagination."""
    total = int(await db.library.count_files())
    if total <= 0:
        return []
    return _narrow_tag_list(await db.library.list_files(limit=total))


async def _library_files(db: Database, library_id: int | None) -> list[dict[str, Any]]:
    """Return file documents scoped to one library or the whole collection."""
    if library_id is not None:
        return _narrow_tag_list(await db.library.list_library_files(library_id))
    return await _all_library_files(db)


async def _tag_file_ids(db: Database, tag_id: int) -> set[int]:
    """Return file ids linked to one tag via the intent-level library facade."""
    tag_doc = await get_tag(db, tag_id)
    if tag_doc is None:
        return set()
    tag_name = tag_doc.get("name")
    tag_value = tag_doc.get("value")
    if not isinstance(tag_name, str) or tag_value is None:
        return set()
    return {
        file_id
        for file_doc in _narrow_tag_list(
            await db.library.search_files_by_tag(tag_name, str(tag_value), limit=None),
        )
        if isinstance((file_id := file_doc.get("id")), int)
    }


async def _song_count_for_tag(db: Database, tag_id: int) -> int:
    """Count songs targeting one tag via the intent-level library facade."""
    return len(await _tag_file_ids(db, tag_id))


async def _song_count_rows_for_tag_ids(db: Database, tag_ids: list[int]) -> dict[int, int]:
    """Return ``tag_id -> song_count`` using one batched edge lookup."""
    valid_tag_ids = [tag_id for tag_id in tag_ids if isinstance(tag_id, int)]
    if not valid_tag_ids:
        return {}

    count_by_tag_id = dict.fromkeys(valid_tag_ids, 0)
    for edge in _narrow_tag_list(
        await db.library.list_file_tag_edges(valid_tag_ids),
    ):
        if isinstance(tag_id := edge.get("tag_id"), int) and tag_id in count_by_tag_id:
            count_by_tag_id[tag_id] += 1
    return count_by_tag_id


async def _scoped_song_count_for_tag(
    db: Database,
    tag_id: int,
    library_file_ids: set[int] | None,
) -> int:
    """Count songs for a tag, optionally intersected with a library file-id set."""
    if library_file_ids is None:
        return await _song_count_for_tag(db, tag_id)
    if not library_file_ids:
        return 0
    return sum(1 for file_id in await _tag_file_ids(db, tag_id) if file_id in library_file_ids)


def _numeric_value(value: object) -> float | None:
    """Convert loosely numeric values into float form when possible."""
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


def _coerce_sum_value(value: object) -> float:
    """Return numeric values for aggregate sums, treating missing values as zero."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


async def get_unique_names(db: Database, nomarr_only: bool = False) -> list[str]:
    """Return all unique tag name values."""
    total_tags = int(await db.library.count_tags())
    raw_names = await db.library.list_all_tag_names(limit=total_tags)
    names = [str(value) for value in raw_names] if isinstance(raw_names, list) else []
    if nomarr_only:
        names = [name for name in names if name.startswith("nom:")]
    return names


async def get_tag_value_counts(db: Database, name: str) -> dict[Any, int]:
    """Return value → song-count mapping for one tag name."""
    total = int(await db.library.count_tags())
    tag_docs = _narrow_tag_list(await db.library.list_tags(name=name, limit=total)) if total > 0 else []
    count_by_tag_id = await _song_count_rows_for_tag_ids(
        db,
        [tag_id for tag in tag_docs if isinstance(tag_id := tag.get("id"), int)],
    )
    return {
        tag["value"]: count_by_tag_id.get(tag_id, 0)
        for tag in tag_docs
        if isinstance(tag_id := tag.get("id"), int) and "value" in tag
    }


async def get_all_tag_stats_batched(db: Database) -> dict[str, dict[str, Any]]:
    """Return summary stats for all tag names in one query."""
    result: dict[str, dict[str, Any]] = {}
    total_tags = int(await db.library.count_tags())
    if total_tags <= 0:
        return result

    raw_names = await db.library.list_all_tag_names(limit=total_tags)
    tag_names = [str(name_value) for name_value in raw_names] if isinstance(raw_names, list) else []
    all_tag_docs = _narrow_tag_list(await db.library.list_tags(limit=total_tags)) if tag_names else []
    count_by_tag_id = await _song_count_rows_for_tag_ids(
        db,
        [tag_id for tag in all_tag_docs if isinstance(tag_id := tag.get("id"), int)],
    )
    tags_by_name: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for tag in all_tag_docs:
        tag_name = tag.get("name")
        if isinstance(tag_name, str):
            tags_by_name[tag_name].append(tag)

    for name in tag_names:
        values: dict[Any, int] = {
            tag["value"]: count_by_tag_id.get(tag_id, 0)
            for tag in tags_by_name.get(name, [])
            if isinstance(tag_id := tag.get("id"), int) and "value" in tag
        }
        total_count = sum(values.values())
        if values:
            numeric_values = [value for value in values if isinstance(value, int | float)]
            if numeric_values and len(numeric_values) > len(values) / 2:
                first_numeric = numeric_values[0]
                tag_type = "float" if isinstance(first_numeric, float) else "integer"
            else:
                tag_type = "string"
        else:
            tag_type = "unknown"
        if tag_type in {"float", "integer"}:
            numeric_vals = [value for value in values if isinstance(value, int | float)]
            summary = (
                f"min={min(numeric_vals)}, max={max(numeric_vals)}, unique={len(numeric_vals)}"
                if numeric_vals
                else "no values"
            )
        else:
            summary = f"unique={len(values)}"
        result[name] = {
            "type": tag_type,
            "is_multivalue": len(values) > 1,
            "summary": summary,
            "total_count": total_count,
        }
    return result


async def get_tag_frequencies(db: Database, limit: int, namespace_prefix: str) -> dict[str, Any]:
    """Return frequency inputs for analytics service."""
    total_tags = int(await db.library.count_tags())
    nom_counts: defaultdict[str, int] = defaultdict(int)
    genre_counts: defaultdict[str, int] = defaultdict(int)

    if total_tags > 0:
        raw_names = await db.library.list_all_tag_names(limit=total_tags)
        tag_names = [str(name_value) for name_value in raw_names] if isinstance(raw_names, list) else []
        relevant_names = [name for name in tag_names if name.startswith("nom:") or name == "genre"]
        all_tag_docs = (
            [
                tag
                for tag in _narrow_tag_list(await db.library.list_tags(limit=total_tags))
                if tag.get("name") in relevant_names
            ]
            if relevant_names
            else []
        )
        count_by_tag_id = await _song_count_rows_for_tag_ids(
            db,
            [tag_id for tag in all_tag_docs if isinstance(tag_id := tag.get("id"), int)],
        )

        for tag in all_tag_docs:
            tag_id = tag.get("id")
            tag_name = tag.get("name")
            tag_value = tag.get("value")
            if not isinstance(tag_id, int) or not isinstance(tag_name, str):
                continue
            song_count = count_by_tag_id.get(tag_id, 0)
            if song_count <= 0:
                continue
            if tag_name.startswith("nom:"):
                key_part = tag_name.removeprefix(namespace_prefix)
                nom_counts[f"{key_part}:{tag_value}"] += song_count
            elif tag_name == "genre" and isinstance(tag_value, str):
                genre_counts[tag_value] += song_count

    nom_tag_rows = sorted(nom_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    genre_rows = sorted(genre_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return {"nom_tag_rows": nom_tag_rows, "genre_rows": genre_rows}


async def get_library_stats(db: Database, library_id: int | None = None) -> dict[str, Any]:
    """Return aggregate collection stats for the whole library or one library."""
    files = await _library_files(db, library_id)
    if not files:
        return {
            "file_count": 0,
            "total_duration_ms": 0,
            "total_file_size_bytes": 0,
            "avg_track_length_ms": 0,
        }

    file_count = len(files)
    total_duration_s = sum(_coerce_sum_value(file_doc.get("duration_seconds")) for file_doc in files)
    total_size = sum(int(_coerce_sum_value(file_doc.get("file_size"))) for file_doc in files)
    return {
        "file_count": file_count,
        "total_duration_ms": floor(total_duration_s * 1000),
        "total_file_size_bytes": total_size,
        "avg_track_length_ms": (total_duration_s / file_count) * 1000 if file_count > 0 else 0,
    }


async def get_year_distribution(db: Database, library_id: int | None = None) -> list[dict[str, Any]]:
    """Return year distribution rows for collection overview."""
    total_tags = int(await db.library.count_tags())
    if total_tags <= 0:
        return []

    library_file_ids: set[int] | None = None
    if library_id is not None:
        library_file_ids = {
            file_id
            for file_doc in _narrow_tag_list(await db.library.list_library_files(library_id))
            if isinstance(file_id := file_doc.get("id"), int)
        }
    total_year = int(await db.library.count_tags())
    year_tags = _narrow_tag_list(await db.library.list_tags(name="year", limit=total_year)) if total_year > 0 else []
    count_by_tag_id = (
        await _song_count_rows_for_tag_ids(
            db,
            [tag_id for tag in year_tags if isinstance(tag_id := tag.get("id"), int)],
        )
        if library_file_ids is None
        else {}
    )
    rows: list[dict[str, Any]] = []
    for tag in year_tags:
        tag_id = tag.get("id")
        if not isinstance(tag_id, int) or "value" not in tag:
            continue
        song_count = (
            count_by_tag_id.get(tag_id, 0)
            if library_file_ids is None
            else await _scoped_song_count_for_tag(db, tag_id, library_file_ids)
        )
        if song_count <= 0:
            continue
        rows.append({"year": tag["value"], "count": song_count})

    rows.sort(
        key=lambda row: (
            _numeric_value(row["year"]) is None,
            _numeric_value(row["year"]) if _numeric_value(row["year"]) is not None else str(row["year"]),
        ),
        reverse=True,
    )
    return rows


async def get_genre_distribution(
    db: Database,
    library_id: int | None = None,
    limit: int | None = 20,
) -> list[dict[str, Any]]:
    """Return genre distribution rows for collection overview."""
    total_tags = int(await db.library.count_tags())
    if total_tags <= 0:
        return []

    library_file_ids: set[int] | None = None
    if library_id is not None:
        library_file_ids = {
            file_id
            for file_doc in _narrow_tag_list(await db.library.list_library_files(library_id))
            if isinstance(file_id := file_doc.get("id"), int)
        }
    total_genre = int(await db.library.count_tags())
    genre_tags = (
        _narrow_tag_list(await db.library.list_tags(name="genre", limit=total_genre)) if total_genre > 0 else []
    )
    count_by_tag_id: dict[int, int] = (
        await _song_count_rows_for_tag_ids(
            db,
            [
                tag_id
                for tag in genre_tags
                if isinstance(tag_id := tag.get("id"), int) and isinstance(tag.get("value"), str)
            ],
        )
        if library_file_ids is None
        else {}
    )
    rows: list[dict[str, Any]] = []
    for tag in genre_tags:
        tag_id = tag.get("id")
        genre_value = tag.get("value")
        if not isinstance(tag_id, int) or not isinstance(genre_value, str):
            continue
        song_count = (
            count_by_tag_id.get(tag_id, 0)
            if library_file_ids is None
            else await _scoped_song_count_for_tag(db, tag_id, library_file_ids)
        )
        if song_count <= 0:
            continue
        rows.append({"genre": genre_value, "count": song_count})

    rows.sort(key=lambda row: (-int(row["count"]), str(row["genre"]).lower()))
    if limit is not None:
        return rows[:limit]
    return rows
