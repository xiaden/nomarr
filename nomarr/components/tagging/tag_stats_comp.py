"""Tag statistics helpers built on the intent-level library persistence facade.

All reads route through the sealed tag facade using domain values
(``TagRef`` / ``TagUsage`` / ``Song``). Tag "counts" come from
``list_tags_with_song_count`` (typed ``TagUsage``), never from materializing tag
ids or song-tag edges. Library scopes filter song locators on their
``LibraryIdentity.library_uuid``; no generated id is derived from ``Song``.
"""

from __future__ import annotations

from collections import defaultdict
from math import floor
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_song_query_comp import locators_for_carriers
from nomarr.components.library.song_query_types import TrackSong
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
    from nomarr.persistence.db import Database


def _library_identity(library: Library) -> LibraryIdentity:
    """Build the immutable ``LibraryIdentity`` for one domain ``Library``."""
    if library.library_uuid is None:
        raise ValueError(f"Library {library.name!r} has no library_uuid")
    return LibraryIdentity(
        library_uuid=library.library_uuid,
        name=library.name,
        root_path=library.root_path,
    )


def _all_songs(db: Database) -> list[Song]:
    """Return every library's semantic songs across the whole collection.

    The intent-level facade has no global ``list_songs`` (song listing requires a
    ``LibraryIdentity``), so a whole-collection listing is assembled by iterating
    the known libraries and collecting each library's songs.
    """
    songs: list[Song] = []
    for library in db.library.list_libraries():
        if library.library_uuid is None:
            continue
        songs.extend(db.library.list_songs(_library_identity(library), limit=None))
    return songs


def _songs(db: Database, library: Library | None) -> list[Song]:
    """Return semantic songs scoped to one library or the whole collection."""
    if library is not None:
        return list(db.library.list_songs(_library_identity(library), limit=None))
    return _all_songs(db)


def _project_song_locators(db: Database, songs: Sequence[Song]) -> list[SongIdentity]:
    """Project bare semantic songs to their UUID-bearing locators in input order.

    Uses the Q3-C public projection :func:`locators_for_carriers`; unresolved
    songs are skipped deterministically. No generated id, row, resolver, or
    physical-path heuristic participates.
    """
    if not songs:
        return []
    carriers = [TrackSong(song=song, metadata={}, isrc=None) for song in songs]
    return [locator for locator in locators_for_carriers(db, carriers) if locator is not None]


def _scoped_song_count_for_tag(
    db: Database,
    identity: TagRef,
    library: Library | None,
) -> int:
    """Count songs for a tag identity, scoped to one library by locator uuid.

    Global scope (``library is None``) uses the aggregate facade count. A scoped
    count projects the tag's songs to locators through the public carrier
    projection and keeps only the locators owned by the requested library — no
    integer library-song-id bridge and no generated id comparison.
    """
    songs = db.library.find_songs_with_tag(identity, limit=None)
    if library is None:
        return len(songs)
    locators = _project_song_locators(db, songs)
    return sum(1 for locator in locators if locator.library.library_uuid == library.library_uuid)


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


def get_unique_names(db: Database, nomarr_only: bool = False) -> list[str]:
    """Return all unique tag name values."""
    total_tags = int(db.library.count_tags())
    raw_names = db.library.list_all_tag_names(limit=total_tags)
    names = [str(value) for value in raw_names]
    if nomarr_only:
        names = [name for name in names if name.startswith("nom:")]
    return names


def get_tag_value_counts(db: Database, name: str) -> dict[Any, int]:
    """Return value → song-count mapping for one tag name."""
    total = int(db.library.count_tags_filtered(name=name))
    if total <= 0:
        return {}
    usages = db.library.list_tags_with_song_count(name=name, limit=total, offset=0)
    return {usage.identity.value: usage.song_count for usage in usages}


def get_all_tag_stats_batched(db: Database) -> dict[str, dict[str, Any]]:
    """Return summary stats for all tag names in one query."""
    result: dict[str, dict[str, Any]] = {}
    total_tags = int(db.library.count_tags())
    if total_tags <= 0:
        return result

    all_usages = list(db.library.list_tags_with_song_count(limit=total_tags, offset=0))
    tags_by_name: defaultdict[str, list[Any]] = defaultdict(list)
    for usage in all_usages:
        tags_by_name[usage.identity.name].append(usage)

    for name, usages in tags_by_name.items():
        values: dict[Any, int] = {usage.identity.value: usage.song_count for usage in usages}
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
    total_tags = int(db.library.count_tags())
    nom_counts: defaultdict[str, int] = defaultdict(int)
    genre_counts: defaultdict[str, int] = defaultdict(int)

    if total_tags > 0:
        all_usages = [
            usage
            for usage in db.library.list_tags_with_song_count(limit=total_tags, offset=0)
            if usage.identity.namespace == "nom" or usage.identity.name == "genre"
        ]

        for usage in all_usages:
            song_count = usage.song_count
            if song_count <= 0:
                continue
            identity = usage.identity
            if identity.namespace == "nom":
                key_part = identity.name.removeprefix(namespace_prefix)
                nom_counts[f"{key_part}:{identity.value}"] += song_count
            elif identity.name == "genre" and isinstance(identity.value, str):
                genre_counts[identity.value] += song_count

    nom_tag_rows = sorted(nom_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    genre_rows = sorted(genre_counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return {"nom_tag_rows": nom_tag_rows, "genre_rows": genre_rows}


def get_library_stats(db: Database, library: Library | None = None) -> dict[str, Any]:
    """Return aggregate collection stats for the whole library or one library."""
    files = _songs(db, library)
    if not files:
        return {
            "file_count": 0,
            "total_duration_ms": 0,
            "total_file_size_bytes": 0,
            "avg_track_length_ms": 0,
        }

    file_count = len(files)
    total_duration_s = sum(_coerce_sum_value(song.duration_seconds) for song in files)
    total_size = sum(int(_coerce_sum_value(song.file_size)) for song in files)
    return {
        "file_count": file_count,
        "total_duration_ms": floor(total_duration_s * 1000),
        "total_file_size_bytes": total_size,
        "avg_track_length_ms": (total_duration_s / file_count) * 1000 if file_count > 0 else 0,
    }


def get_year_distribution(db: Database, library: Library | None = None) -> list[dict[str, Any]]:
    """Return year distribution rows for collection overview."""
    total_year = int(db.library.count_tags_filtered(name="year"))
    if total_year <= 0:
        return []

    year_usages = db.library.list_tags_with_song_count(name="year", limit=total_year, offset=0)
    rows: list[dict[str, Any]] = []
    for usage in year_usages:
        song_count = usage.song_count if library is None else _scoped_song_count_for_tag(db, usage.identity, library)
        if song_count <= 0:
            continue
        rows.append({"year": usage.identity.value, "count": song_count})

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
    library: Library | None = None,
    limit: int | None = 20,
) -> list[dict[str, Any]]:
    """Return genre distribution rows for collection overview."""
    total_genre = int(db.library.count_tags_filtered(name="genre"))
    if total_genre <= 0:
        return []

    genre_usages = db.library.list_tags_with_song_count(name="genre", limit=total_genre, offset=0)
    rows: list[dict[str, Any]] = []
    for usage in genre_usages:
        genre_value = usage.identity.value
        if not isinstance(genre_value, str):
            continue
        song_count = usage.song_count if library is None else _scoped_song_count_for_tag(db, usage.identity, library)
        if song_count <= 0:
            continue
        rows.append({"genre": genre_value, "count": song_count})

    rows.sort(key=lambda row: (-int(row["count"]), str(row["genre"]).lower()))
    if limit is not None:
        return rows[:limit]
    return rows
