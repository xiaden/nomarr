"""Entity seeding component - derive entities from raw metadata tags.

Converts raw metadata strings into tag relationships via component-owned tag helpers.
Part of hybrid model: seed edges from imports, then rebuild cache.
"""

import logging
from typing import TYPE_CHECKING, Any, TypedDict

from nomarr.components.tagging.tag_parsing_comp import parse_tag_values
from nomarr.components.tagging.tag_write_comp import set_song_tags, set_song_tags_batch
from nomarr.helpers.dto.tags_dto import TagValue

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


class _TagEntry(TypedDict):
    """Internal shape for batched tag-write entries."""

    song_id: str
    name: str
    values: list[TagValue]


def _derive_artists(tags: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Derive singular artist and artist list from raw mutagen tag dict.

    Returns ``(primary_artist, all_artists)`` where *primary_artist* is a
    single string or ``None``, and *all_artists* is a (possibly empty) list.
    """
    artist_raw = tags.get("artist")
    artists_raw = tags.get("artists")
    primary_artist: str | None = None
    if artist_raw:
        primary_artist = (artist_raw[0] if artist_raw else None) if isinstance(artist_raw, list) else artist_raw
    elif artists_raw:
        primary_artist = (artists_raw[0] if artists_raw else None) if isinstance(artists_raw, list) else artists_raw
    all_artists: list[str] = []
    if artists_raw:
        all_artists = [str(a) for a in artists_raw if a] if isinstance(artists_raw, list) else [str(artists_raw)]
    elif primary_artist:
        all_artists = [primary_artist]
    return primary_artist, all_artists


def seed_song_entities_from_tags(db: "Database", song_id: str, tags: dict[str, Any]) -> None:
    """Derive tag relationships from raw imported metadata tags.

    Supports artist, artists (multi), album, label, genre, and year.
    """
    # --- artist (singular) ---
    primary_artist, all_artists = _derive_artists(tags)
    set_song_tags(db, song_id, "artist", [primary_artist] if primary_artist else [])

    # --- artists (multi) ---
    set_song_tags(db, song_id, "artists", list(all_artists))

    # --- album (singular) ---
    album_raw = tags.get("album")
    if album_raw:
        album_str = album_raw[0] if isinstance(album_raw, list) else album_raw
        set_song_tags(db, song_id, "album", [album_str])
    else:
        set_song_tags(db, song_id, "album", [])

    # --- label (multi) ---
    label_raw = tags.get("label")
    labels: list[str] = []
    if label_raw:
        if isinstance(label_raw, list):
            labels = [str(label_item) for label_item in label_raw if label_item]
        else:
            labels = [str(label_raw)]
    set_song_tags(db, song_id, "label", list(labels))

    # --- genre (multi) ---
    genre_raw = tags.get("genre")
    genres: list[str] = []
    if genre_raw:
        genres = [str(g) for g in genre_raw if g] if isinstance(genre_raw, list) else [str(genre_raw)]
    set_song_tags(db, song_id, "genre", list(genres))

    # --- year (singular) ---
    year_raw = tags.get("year")
    if year_raw:
        year_int = year_raw if isinstance(year_raw, int) else int(year_raw)
        set_song_tags(db, song_id, "year", [year_int])
    else:
        set_song_tags(db, song_id, "year", [])


_ENTITY_TAG_KEYS = ("artist", "artists", "album", "label", "genre", "year")


def _extract_entity_tags(metadata: dict[str, Any]) -> dict[str, Any]:
    """Extract entity-relevant tag keys from scan metadata."""
    return {k: metadata.get(k) for k in _ENTITY_TAG_KEYS}


def _build_song_tag_entries(song_id: str, tags: dict[str, Any]) -> list[_TagEntry]:
    """Build tag entries for batch-seeding from raw entity tags.

    Mirrors the normalization logic in :func:`seed_song_entities_from_tags`
    but collects entries instead of calling the DB per-name.
    """
    entries: list[_TagEntry] = []

    # --- artist (singular) ---
    primary_artist, all_artists = _derive_artists(tags)
    entries.append({"song_id": song_id, "name": "artist", "values": [primary_artist] if primary_artist else []})

    # --- artists (multi) ---
    entries.append({"song_id": song_id, "name": "artists", "values": list(all_artists)})

    # --- album (singular) ---
    album_raw = tags.get("album")
    if album_raw:
        album_str = album_raw[0] if isinstance(album_raw, list) else album_raw
        entries.append({"song_id": song_id, "name": "album", "values": [album_str]})
    else:
        entries.append({"song_id": song_id, "name": "album", "values": []})

    # --- label (multi) ---
    label_raw = tags.get("label")
    labels: list[str] = []
    if label_raw:
        labels = [str(lbl) for lbl in label_raw if lbl] if isinstance(label_raw, list) else [str(label_raw)]
    entries.append({"song_id": song_id, "name": "label", "values": list(labels)})

    # --- genre (multi) ---
    genre_raw = tags.get("genre")
    genres: list[str] = []
    if genre_raw:
        genres = [str(g) for g in genre_raw if g] if isinstance(genre_raw, list) else [str(genre_raw)]
    entries.append({"song_id": song_id, "name": "genre", "values": list(genres)})

    # --- year (singular) ---
    year_raw = tags.get("year")
    if year_raw:
        year_int = year_raw if isinstance(year_raw, int) else int(year_raw)
        entries.append({"song_id": song_id, "name": "year", "values": [year_int]})
    else:
        entries.append({"song_id": song_id, "name": "year", "values": []})

    return entries


def _build_entity_tag_map(tags: dict[str, Any]) -> dict[str, list[TagValue]]:
    """Return canonical entity-tag values keyed by tag name.

    Uses the same normalization logic as :func:`seed_song_entities_from_tags`,
    but materialises the result as a mapping so batch scan persistence can merge
    it with the full raw tag set before writing everything in one call.
    """
    return {str(entry["name"]): list(entry["values"]) for entry in _build_song_tag_entries(song_id="", tags=tags)}


def _build_scan_tag_map(metadata: dict[str, Any]) -> dict[str, list[TagValue]]:
    """Build the authoritative persisted tag map for one scanned file.

    Persists extracted source tags, adds structured genre/year/track_number,
    persists namespaced Nomarr tags, and overrides entity tags with canonical
    values.
    """
    all_tags = dict(metadata.get("all_tags", {}))
    nom_tags = metadata.get("nom_tags", {})

    if metadata.get("genre"):
        all_tags["genre"] = metadata["genre"]
    if metadata.get("year") is not None:
        all_tags["year"] = metadata["year"]
    if metadata.get("track_number") is not None:
        all_tags["track_number"] = metadata["track_number"]

    persisted_tags: dict[str, list[TagValue]] = parse_tag_values(all_tags) if all_tags else {}
    if nom_tags:
        parsed_nom_tags = parse_tag_values(nom_tags)
        for name, values in parsed_nom_tags.items():
            tag_name = name if name.startswith("nom:") else f"nom:{name}"
            persisted_tags[tag_name] = values

    entity_tags = _build_entity_tag_map(_extract_entity_tags(metadata))
    persisted_tags |= {name: values for name, values in entity_tags.items() if values or name in metadata}

    return persisted_tags


def seed_entities_for_scan_batch(
    db: "Database",
    file_ids: list[str],
    metadata_by_id: dict[str, dict[str, Any]],
) -> int:
    """Persist scan-derived tags for scanned files.

    Batch-optimised: collects per-file tag entries in-memory, then executes
    ``set_song_tags_batch`` once.
    """
    if not file_ids:
        return 0

    all_tag_entries: list[dict[str, Any]] = []
    files_processed = 0

    for file_id in file_ids:
        metadata = metadata_by_id.get(file_id)

        if not metadata:
            logger.warning("No metadata for file_id: %s", file_id)
            continue

        try:
            persisted_tags = _build_scan_tag_map(metadata)
            all_tag_entries.extend(
                {"song_id": file_id, "name": str(name), "values": list(values)}
                for name, values in persisted_tags.items()
            )
            files_processed += 1
        except (TypeError, ValueError, KeyError) as e:
            logger.warning("Failed to build entities for file_id %s: %s", file_id, e)

    if all_tag_entries:
        try:
            set_song_tags_batch(db, all_tag_entries)
        except Exception as e:
            # Broad catch: set_song_tags_batch delegates to the DB layer which
            # may raise any persistence-related exception type. We log and
            # return zero to let the caller decide retry/error handling.
            logger.warning("Batch tag persistence failed: %s", e)
            return 0

    return files_processed
