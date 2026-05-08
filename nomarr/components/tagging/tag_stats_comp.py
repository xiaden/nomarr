"""Tag statistics helpers extracted from legacy tag persistence."""

from __future__ import annotations

from collections import defaultdict
from math import floor
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _tags_ns(db: Database) -> Any:
    """Return the runtime-wired tags namespace with collection verbs attached."""
    return cast("Any", db.tags)


def _library_files_ns(db: Database) -> Any:
    """Return the runtime-wired library-files namespace with collection verbs attached."""
    return cast("Any", db.library_files)


def _libraries_ns(db: Database) -> Any:
    """Return the runtime-wired libraries namespace with traversal verbs attached."""
    return cast("Any", db.libraries)


def _song_has_tags_ns(db: Database) -> Any:
    """Return the runtime-wired tag-edge namespace with collection verbs attached."""
    return cast("Any", db.song_has_tags)


def _tags_for_name(db: Database, name: str) -> list[dict[str, Any]]:
    """Return all tags for one tag name."""
    tags = _tags_ns(db)
    total = int(tags.count())
    if total <= 0:
        return []
    return cast("list[dict[str, Any]]", tags.get(name=name, limit=total))


def _all_library_files(db: Database) -> list[dict[str, Any]]:
    """Return all library file documents with explicit pagination."""
    library_files = _library_files_ns(db)
    total = int(library_files.count())
    if total <= 0:
        return []

    page_size = min(total, 1000)
    files: list[dict[str, Any]] = []
    current_offset = 0
    while current_offset < total:
        page_ids = [
            str(row["value"])
            for row in cast(
                "list[dict[str, Any]]", library_files.aggregate("_id", limit=page_size, offset=current_offset)
            )
            if isinstance(row.get("value"), str)
        ]
        page = [
            file_doc
            for file_id in page_ids
            if (file_doc := cast("dict[str, Any] | None", library_files.get(_id=file_id))) is not None
        ]
        if not page:
            break
        files.extend(page)
        current_offset += len(page)
    return files


def _library_files(db: Database, library_id: str | None) -> list[dict[str, Any]]:
    """Return file documents scoped to one library or the whole collection."""
    if library_id is not None:
        libraries = _libraries_ns(db)
        return cast("list[dict[str, Any]]", libraries.library_contains_file(library_id))
    return _all_library_files(db)


def _library_file_ids(db: Database, library_id: str | None) -> set[str] | None:
    """Return the scoped library file-id set when needed."""
    if library_id is None:
        return None
    libraries = _libraries_ns(db)
    return {
        file_id
        for file_doc in cast("list[dict[str, Any]]", libraries.library_contains_file(library_id))
        if isinstance(file_id := file_doc.get("_id"), str)
    }


def _song_count_for_tag(db: Database, tag_id: str) -> int:
    """Count song edges targeting one tag."""
    song_has_tags = _song_has_tags_ns(db)
    return int(song_has_tags.count(_to=tag_id))


def _song_count_rows_for_tag_ids(db: Database, tag_ids: list[str]) -> dict[str, int]:
    """Return ``tag_id -> song_count`` using the generic inbound count verb."""
    if not tag_ids:
        return {}
    tags = _tags_ns(db)
    count_rows = cast(
        "list[dict[str, Any]]",
        tags.count_inbound_connections(
            "song_has_tags",
            filter_field="_id",
            filter_values=tag_ids,
            return_field="_id",
            label="tag_id",
            limit=len(tag_ids),
        ),
    )
    return {str(tag_id): int(row.get("count", 0)) for row in count_rows if (tag_id := row.get("tag_id")) is not None}


def _scoped_song_count_for_tag(
    db: Database,
    tag_id: str,
    library_file_ids: set[str] | None,
    edge_limit: int,
) -> int:
    """Count songs for a tag, optionally intersected with a library file-id set."""
    if library_file_ids is None:
        return _song_count_for_tag(db, tag_id)
    if edge_limit <= 0 or not library_file_ids:
        return 0
    song_has_tags = _song_has_tags_ns(db)
    return sum(
        1
        for edge in cast("list[dict[str, Any]]", song_has_tags.get(_to=tag_id, limit=edge_limit))
        if isinstance(edge.get("_from"), str) and edge["_from"] in library_file_ids
    )


def _numeric_value(value: Any) -> float | None:
    """Convert loosely numeric values into float form when possible."""
    if isinstance(value, bool):
        return None
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


def _coerce_sum_value(value: Any) -> float:
    """Return numeric values for aggregate sums, treating missing values as zero."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def get_unique_names(db: Database, nomarr_only: bool = False) -> list[str]:
    """Return all unique tag name values."""
    tags = _tags_ns(db)
    total_tags = int(tags.count())
    names = [
        str(value)
        for row in cast("list[dict[str, Any]]", tags.aggregate("name", limit=total_tags))
        if (value := row.get("value")) is not None
    ]
    if nomarr_only:
        names = [name for name in names if name.startswith("nom:")]
    return names


def get_tag_value_counts(db: Database, name: str) -> dict[Any, int]:
    """Return value → song-count mapping for one tag name."""
    tag_docs = _tags_for_name(db, name)
    count_by_tag_id = _song_count_rows_for_tag_ids(
        db,
        [tag_id for tag in tag_docs if isinstance(tag_id := tag.get("_id"), str)],
    )
    return {
        tag["value"]: count_by_tag_id.get(tag_id, 0)
        for tag in tag_docs
        if isinstance(tag_id := tag.get("_id"), str) and "value" in tag
    }


def get_all_tag_stats_batched(db: Database) -> dict[str, dict[str, Any]]:
    """Return summary stats for all tag names in one query."""
    tags = _tags_ns(db)
    _library_files_ns(db)
    result: dict[str, dict[str, Any]] = {}
    total_tags = int(tags.count())
    if total_tags <= 0:
        return result

    name_rows = cast("list[dict[str, Any]]", tags.aggregate("name", limit=total_tags))
    tag_names = [str(name_value) for row in name_rows if (name_value := row.get("value")) is not None]
    all_tag_docs = cast("list[dict[str, Any]]", tags.get.in_(name=tag_names, limit=total_tags)) if tag_names else []
    count_by_tag_id = _song_count_rows_for_tag_ids(
        db,
        [tag_id for tag in all_tag_docs if isinstance(tag_id := tag.get("_id"), str)],
    )
    tags_by_name: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for tag in all_tag_docs:
        tag_name = tag.get("name")
        if isinstance(tag_name, str):
            tags_by_name[tag_name].append(tag)

    for row in name_rows:
        name_value = row.get("value")
        if name_value is None:
            continue
        name = str(name_value)
        values: dict[Any, int] = {
            tag["value"]: count_by_tag_id.get(tag_id, 0)
            for tag in tags_by_name.get(name, [])
            if isinstance(tag_id := tag.get("_id"), str) and "value" in tag
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


def get_tag_frequencies(db: Database, limit: int, namespace_prefix: str) -> dict[str, Any]:
    """Return frequency inputs for analytics service."""
    tags = _tags_ns(db)
    total_tags = int(tags.count())
    nom_counts: defaultdict[str, int] = defaultdict(int)
    genre_counts: defaultdict[str, int] = defaultdict(int)

    if total_tags > 0:
        tag_names = [
            str(name_value)
            for row in cast("list[dict[str, Any]]", tags.aggregate("name", limit=total_tags))
            if (name_value := row.get("value")) is not None
        ]
        relevant_names = [name for name in tag_names if name.startswith("nom:") or name == "genre"]
        all_tag_docs = (
            cast("list[dict[str, Any]]", tags.get.in_(name=relevant_names, limit=total_tags)) if relevant_names else []
        )
        count_by_tag_id = _song_count_rows_for_tag_ids(
            db,
            [tag_id for tag in all_tag_docs if isinstance(tag_id := tag.get("_id"), str)],
        )

        for tag in all_tag_docs:
            tag_id = tag.get("_id")
            tag_name = tag.get("name")
            tag_value = tag.get("value")
            if not isinstance(tag_id, str) or not isinstance(tag_name, str):
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


def get_library_stats(db: Database, library_id: str | None = None) -> dict[str, Any]:
    """Return aggregate collection stats for the whole library or one library."""
    files = _library_files(db, library_id)
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


def get_year_distribution(db: Database, library_id: str | None = None) -> list[dict[str, Any]]:
    """Return year distribution rows for collection overview."""
    tags = _tags_ns(db)
    total_tags = int(tags.count())
    if total_tags <= 0:
        return []

    library_file_ids = _library_file_ids(db, library_id)
    song_has_tags = _song_has_tags_ns(db)
    edge_limit = int(song_has_tags.count()) if library_file_ids is not None else 0
    year_tags = cast("list[dict[str, Any]]", tags.get(name="year", limit=total_tags))
    count_by_tag_id = (
        _song_count_rows_for_tag_ids(
            db,
            [tag_id for tag in year_tags if isinstance(tag_id := tag.get("_id"), str)],
        )
        if library_file_ids is None
        else {}
    )
    rows: list[dict[str, Any]] = []
    for tag in year_tags:
        tag_id = tag.get("_id")
        if not isinstance(tag_id, str) or "value" not in tag:
            continue
        song_count = (
            count_by_tag_id.get(tag_id, 0)
            if library_file_ids is None
            else _scoped_song_count_for_tag(db, tag_id, library_file_ids, edge_limit)
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


def get_genre_distribution(
    db: Database,
    library_id: str | None = None,
    limit: int | None = 20,
) -> list[dict[str, Any]]:
    """Return genre distribution rows for collection overview."""
    tags = _tags_ns(db)
    total_tags = int(tags.count())
    if total_tags <= 0:
        return []

    library_file_ids = _library_file_ids(db, library_id)
    song_has_tags = _song_has_tags_ns(db)
    edge_limit = int(song_has_tags.count()) if library_file_ids is not None else 0
    genre_tags = cast("list[dict[str, Any]]", tags.get(name="genre", limit=total_tags))
    count_by_tag_id = (
        _song_count_rows_for_tag_ids(
            db,
            [
                tag_id
                for tag in genre_tags
                if isinstance(tag_id := tag.get("_id"), str) and isinstance(tag.get("value"), str)
            ],
        )
        if library_file_ids is None
        else {}
    )
    rows: list[dict[str, Any]] = []
    for tag in genre_tags:
        tag_id = tag.get("_id")
        genre_value = tag.get("value")
        if not isinstance(tag_id, str) or not isinstance(genre_value, str):
            continue
        song_count = (
            count_by_tag_id.get(tag_id, 0)
            if library_file_ids is None
            else _scoped_song_count_for_tag(db, tag_id, library_file_ids, edge_limit)
        )
        if song_count <= 0:
            continue
        rows.append({"genre": genre_value, "count": song_count})

    rows.sort(key=lambda row: (-int(row["count"]), str(row["genre"]).lower()))
    if limit is not None:
        return rows[:limit]
    return rows
