"""Entity seeding component - derive entities from raw metadata tags.

Converts raw metadata strings into song tag edges via unified TagOperations API.
Part of hybrid model: seed edges from imports, then rebuild cache.
"""

import logging
from typing import TYPE_CHECKING, Any

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


def seed_entities_for_scan_batch(
    db: "Database",
    file_paths: list[str],
    metadata_map: dict[str, dict[str, Any]],
) -> int:
    """Seed entity vertices/edges and rebuild metadata caches for scanned files.

    For each file, looks up the DB record, extracts entity tags from metadata,
    calls :func:`seed_song_entities_from_tags`, then rebuilds the metadata cache.

    Args:
        db: Database instance
        file_paths: File paths that were just upserted
        metadata_map: Map of file_path -> raw metadata dict

    Returns:
        Number of files successfully seeded

    """
    from nomarr.components.metadata.metadata_cache_comp import rebuild_song_metadata_cache

    seeded = 0
    for file_path in file_paths:
        metadata = metadata_map.get(file_path)
        if not metadata:
            continue

        file_record = db.library_files.get_library_file(file_path)
        if not file_record:
            logger.warning("File not found after upsert: %s", file_path)
            continue

        file_id = file_record["_id"]

        try:
            entity_tags = _extract_entity_tags(metadata)
            seed_song_entities_from_tags(db, file_id, entity_tags)
            rebuild_song_metadata_cache(db, file_id)
            seeded += 1
        except Exception as e:
            logger.warning("Failed to seed entities for %s: %s", file_path, e)

    return seeded
