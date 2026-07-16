"""Metadata cache rebuild component.

Rebuilds derived song metadata fields from authoritative tags collection.
Part of hybrid entity graph: tags are truth, embedded fields are read cache.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field extractors — pure functions, no DB dependency
# ---------------------------------------------------------------------------


_METADATA_CACHE_FIELDS = {
    "artist",
    "artists",
    "album",
    "labels",
    "genres",
    "year",
    "bpm",
    "key",
    "title",
    "tracknumber",
    "discnumber",
}


def compute_metadata_cache_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    """Extract embedded cache fields from raw metadata.

    Pure function — takes a metadata dict from tag parsing and returns only
    the fields that belong on the song document's embedded cache.

    Args:
        metadata: Raw metadata key-value dict from tag extraction.

    Returns:
        Filtered dict with only cache-relevant fields.

    """
    result: dict[str, Any] = {}
    for key in _METADATA_CACHE_FIELDS:
        value = metadata.get(key)
        if value is not None:
            # Arrays stored as sorted lists
            if isinstance(value, (list, set)):
                sorted_str = sorted(str(v) for v in value)
                result[key] = sorted_str
            elif isinstance(value, str):
                result[key] = value
            else:
                result[key] = value
    return result


def update_metadata_cache_batch(db: Database, updates: list[dict[str, Any]]) -> None:
    """Write metadata cache fields to song documents in batch.

    Each update dict must include a ``song_id`` key identifying the file
    document, plus any of the recognised cache fields.

    Args:
        db: Database instance.
        updates: List of ``{song_id, artist, artists, album, labels,
            genres, year, ...}`` dicts to write.

    """
    from nomarr.helpers.time_helper import now_ms

    now_val = now_ms()
    for update in updates:
        song_id = update.pop("song_id", None)
        if not isinstance(song_id, str):
            continue
        update["_cache_updated_at"] = now_val.value
        db.library.file_repo.update_file(song_id, update)


# ---------------------------------------------------------------------------
# Full-rebuild paths (legacy)
# ---------------------------------------------------------------------------


async def rebuild_song_metadata_cache(db: Database, song_id: str) -> None:
    """Rebuild embedded metadata cache fields on a song from tags.

    Reads all tags for the song and recomputes cache fields.

    Args:
        db: Database handle
        song_id: Song _id (e.g., ``"library_files/12345"``)

    """
    from nomarr.components.tagging.tag_query_comp import get_song_tags

    tags_dict = await get_song_tags(db, song_id).to_dict()

    artists_raw = [str(v) for v in tags_dict.get("artists", [])]
    artist_raw = [str(v) for v in tags_dict.get("artist", [])]
    album_raw = [str(v) for v in tags_dict.get("album", [])]
    label_raw = [str(v) for v in tags_dict.get("label", [])]
    genre_raw = [str(v) for v in tags_dict.get("genre", [])]
    year_raw = [str(v) for v in tags_dict.get("year", [])]

    artist = str(artist_raw[0]) if artist_raw else None
    artists = sorted(str(a) for a in artists_raw) if artists_raw else None
    album = str(album_raw[0]) if album_raw else None
    labels = sorted(str(lbl) for lbl in label_raw) if label_raw else None
    genres = sorted(str(g) for g in genre_raw) if genre_raw else None

    year: int | None = None
    if year_raw:
        try:
            year = int(year_raw[0])
        except (ValueError, TypeError):
            logger.warning("Failed to parse year from tag: %s", year_raw[0])

    fields = {
        k: v
        for k, v in {
            "artist": artist,
            "artists": artists,
            "album": album,
            "labels": labels,
            "genres": genres,
            "year": year,
        }.items()
        if v is not None
    }
    if fields:
        db.library.file_repo.update_file(song_id, fields)


async def rebuild_all_song_metadata_caches(db: Database, limit: int | None = None) -> int:
    """Rebuild metadata caches for every song in the database.

    Args:
        db: Database handle
        limit: Maximum number of songs to rebuild (``None`` = all).

    Returns:
        Count of songs whose cache was rebuilt.

    """
    from nomarr.components.library.library_file_query_comp import list_all_file_ids

    file_ids = await list_all_file_ids(db, limit=limit)
    count = 0
    for file_id in file_ids:
        rebuild_song_metadata_cache(db, file_id)
        count += 1
    return count
