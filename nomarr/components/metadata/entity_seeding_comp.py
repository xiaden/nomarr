"""Entity seeding component - derive entities from raw metadata tags.

Converts raw metadata strings into song tag edges via unified TagOperations API.
Part of hybrid model: seed edges from imports, then rebuild cache.
"""

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.metadata.metadata_cache_comp import (
    compute_metadata_cache_fields,
    update_metadata_cache_batch,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def seed_song_entities_from_tags(db: "Database", song_id: str, tags: dict[str, Any]) -> None:
    """Derive song tag edges from raw imported metadata tags.

    Uses the unified TagOperations API to set tags directly from raw values.

    Supports:
    - artist (singular): tag key "artist" or first from "artists"
    - artists (multi): tag key "artists" or ["artist"] if missing
    - album (singular): tag key "album"
    - label (multi): tag key "label" (list) or single value wrapped
    - genres (multi): tag key "genre" (list) or single value wrapped
    - year (singular): tag key "year" (int)

    Args:
        db: Database handle
        song_id: Song _id (e.g., "library_files/12345")
        tags: Raw metadata tags dict (from mutagen/external source)

    """
    tag_ops = db.tags

    # ==================== ARTIST (singular) ====================
    artist_raw = tags.get("artist")
    artists_raw = tags.get("artists")

    # Derive singular artist: use "artist" if present, else first from "artists"
    primary_artist: str | None = None
    if artist_raw:
        primary_artist = (artist_raw[0] if artist_raw else None) if isinstance(artist_raw, list) else artist_raw
    elif artists_raw:
        primary_artist = (artists_raw[0] if artists_raw else None) if isinstance(artists_raw, list) else artists_raw

    tag_ops.set_song_tags(song_id, "artist", [primary_artist] if primary_artist else [])

    # ==================== ARTISTS (multi) ====================
    # Use "artists" if present, else use ["artist"] if present
    all_artists: list[str] = []
    if artists_raw:
        all_artists = [str(a) for a in artists_raw if a] if isinstance(artists_raw, list) else [str(artists_raw)]
    elif primary_artist:
        all_artists = [primary_artist]

    tag_ops.set_song_tags(song_id, "artists", list(all_artists))

    # ==================== ALBUM (singular) ====================
    album_raw = tags.get("album")
    if album_raw:
        album_str = album_raw[0] if isinstance(album_raw, list) else album_raw
        tag_ops.set_song_tags(song_id, "album", [album_str])
    else:
        tag_ops.set_song_tags(song_id, "album", [])

    # ==================== LABEL (multi) ====================
    label_raw = tags.get("label")
    labels: list[str] = []
    if label_raw:
        if isinstance(label_raw, list):
            labels = [str(label_item) for label_item in label_raw if label_item]
        else:
            labels = [str(label_raw)]

    tag_ops.set_song_tags(song_id, "label", list(labels))

    # ==================== GENRES (multi) ====================
    genre_raw = tags.get("genre")
    genres: list[str] = []
    if genre_raw:
        genres = [str(g) for g in genre_raw if g] if isinstance(genre_raw, list) else [str(genre_raw)]

    tag_ops.set_song_tags(song_id, "genre", list(genres))

    # ==================== YEAR (singular) ====================
    year_raw = tags.get("year")
    if year_raw:
        year_int = year_raw if isinstance(year_raw, int) else int(year_raw)
        tag_ops.set_song_tags(song_id, "year", [year_int])
    else:
        tag_ops.set_song_tags(song_id, "year", [])


_ENTITY_TAG_KEYS = ("artist", "artists", "album", "label", "genre", "year")


def _extract_entity_tags(metadata: dict[str, Any]) -> dict[str, Any]:
    """Extract entity-relevant tag keys from scan metadata.

    Args:
        metadata: Raw file metadata dict (from mutagen)

    Returns:
        Dict with only the entity tag keys

    """
    return {k: metadata.get(k) for k in _ENTITY_TAG_KEYS}


def _build_song_tag_entries(song_id: str, tags: dict[str, Any]) -> list[dict[str, Any]]:
    """Build tag entries for batch-seeding from raw entity tags.

    Returns list of dicts with keys ``song_id``, ``rel``, ``values``
    suitable for :meth:`TagOperations.set_song_tags_batch`.

    Mirrors the normalization logic in :func:`seed_song_entities_from_tags`
    but collects entries instead of calling the DB per-rel.

    """
    entries: list[dict[str, Any]] = []

    artist_raw = tags.get("artist")
    artists_raw = tags.get("artists")

    # — artist (singular) —
    primary_artist: str | None = None
    if artist_raw:
        primary_artist = (artist_raw[0] if artist_raw else None) if isinstance(artist_raw, list) else artist_raw
    elif artists_raw:
        primary_artist = (artists_raw[0] if artists_raw else None) if isinstance(artists_raw, list) else artists_raw

    entries.append({"song_id": song_id, "rel": "artist", "values": [primary_artist] if primary_artist else []})

    # — artists (multi) —
    all_artists: list[str] = []
    if artists_raw:
        all_artists = [str(a) for a in artists_raw if a] if isinstance(artists_raw, list) else [str(artists_raw)]
    elif primary_artist:
        all_artists = [str(primary_artist)]

    entries.append({"song_id": song_id, "rel": "artists", "values": list(all_artists)})

    # — album (singular) —
    album_raw = tags.get("album")
    if album_raw:
        album_str = album_raw[0] if isinstance(album_raw, list) else album_raw
        entries.append({"song_id": song_id, "rel": "album", "values": [album_str]})
    else:
        entries.append({"song_id": song_id, "rel": "album", "values": []})

    # — label (multi) —
    label_raw = tags.get("label")
    labels: list[str] = []
    if label_raw:
        labels = [str(lbl) for lbl in label_raw if lbl] if isinstance(label_raw, list) else [str(label_raw)]
    entries.append({"song_id": song_id, "rel": "label", "values": list(labels)})

    # — genre (multi) —
    genre_raw = tags.get("genre")
    genres: list[str] = []
    if genre_raw:
        genres = [str(g) for g in genre_raw if g] if isinstance(genre_raw, list) else [str(genre_raw)]
    entries.append({"song_id": song_id, "rel": "genre", "values": list(genres)})

    # — year (singular) —
    year_raw = tags.get("year")
    if year_raw:
        year_int = year_raw if isinstance(year_raw, int) else int(year_raw)
        entries.append({"song_id": song_id, "rel": "year", "values": [year_int]})
    else:
        entries.append({"song_id": song_id, "rel": "year", "values": []})

    return entries


def seed_entities_for_scan_batch(
    db: "Database",
    file_ids: list[str],
    metadata_by_id: dict[str, dict[str, Any]],
) -> int:
    """Seed entity vertices/edges and update metadata caches for scanned files.

    Batch-optimised: collects per-file tag entries in-memory, then executes
    ``set_song_tags_batch`` (3 AQL) and ``update_metadata_cache_batch`` (1 AQL)
    — total 4 AQL per folder instead of ~20 x N per file.

    Args:
        db: Database instance
        file_ids: Document _ids for files that were just upserted
        metadata_by_id: Map of file_id -> raw metadata dict

    Returns:
        Number of files successfully seeded

    """
    if not file_ids:
        return 0

    # Build all tag entries and cache updates in-memory (no DB lookups needed)
    all_tag_entries: list[dict[str, Any]] = []
    cache_updates: list[dict[str, Any]] = []

    for file_id in file_ids:
        metadata = metadata_by_id.get(file_id)

        if not metadata:
            logger.warning("No metadata for file_id: %s", file_id)
            continue

        try:
            entity_tags = _extract_entity_tags(metadata)
            all_tag_entries.extend(_build_song_tag_entries(file_id, entity_tags))
            cache_updates.append({"song_id": file_id, **compute_metadata_cache_fields(metadata)})
        except Exception as e:
            logger.warning("Failed to build entities for file_id %s: %s", file_id, e)

    # 3) Batch seed entities (3 AQL total instead of 3 x N x 6)
    if all_tag_entries:
        try:
            db.tags.set_song_tags_batch(all_tag_entries)
        except Exception as e:
            logger.warning("Batch tag seeding failed: %s", e)
            return 0

    # 4) Batch update metadata cache (1 AQL instead of N)
    if cache_updates:
        try:
            update_metadata_cache_batch(db, cache_updates)
        except Exception as e:
            logger.warning("Batch cache update failed: %s", e)

    return len(cache_updates)
