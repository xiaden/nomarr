"""Metadata cache rebuild component.

Rebuilds derived song metadata fields from authoritative tags collection.
Part of hybrid entity graph: tags are truth, embedded fields are read cache.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.library.library_file_mutation_comp import (
    update_metadata_cache,
)
from nomarr.components.library.library_file_query_comp import list_all_file_ids
from nomarr.components.tagging.tag_query_comp import get_song_tags

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def rebuild_song_metadata_cache(db: Database, song_id: str) -> None:
    """Rebuild embedded metadata cache fields on a song from tags.

    Reads tags from tags collection and writes derived fields to song document.
    This is the authoritative repair mechanism for the hybrid model.

    Args:
        db: Database handle
        song_id: Song _id (e.g., "library_files/12345")

    """
    # Fetch all tags for this song as a dict
    tags_dict = get_song_tags(db, song_id).to_dict()

    # Extract metadata from tags (using name names directly)
    # to_dict() returns tuple | Iterable, so cast to list
    artists_raw = [str(v) for v in tags_dict.get("artists", [])]
    artist_raw = [str(v) for v in tags_dict.get("artist", [])]
    album_raw = [str(v) for v in tags_dict.get("album", [])]
    label_raw = [str(v) for v in tags_dict.get("label", [])]
    genre_raw = [str(v) for v in tags_dict.get("genre", [])]
    year_raw = [str(v) for v in tags_dict.get("year", [])]

    # Derive embedded field values
    artist = str(artist_raw[0]) if artist_raw else None
    artists = sorted([str(a) for a in artists_raw]) if artists_raw else None
    album = str(album_raw[0]) if album_raw else None
    labels = sorted([str(lbl) for lbl in label_raw]) if label_raw else None
    genres = sorted([str(g) for g in genre_raw]) if genre_raw else None

    # Year: convert to int if present
    year = None
    if year_raw:
        try:
            year = int(year_raw[0])
        except (ValueError, TypeError):
            logger.warning("Failed to parse year from tag: %s", year_raw[0])

    update_metadata_cache(
        db,
        song_id,
        artist=artist,
        artists=artists,
        album=album,
        labels=labels,
        genres=genres,
        year=year,
    )


def rebuild_all_song_metadata_caches(db: Database, limit: int | None = None) -> int:
    """Rebuild metadata cache for all songs in library.

    Args:
        db: Database handle
        limit: Optional limit for testing (None = all songs)

    Returns:
        Number of songs processed

    """
    song_ids = list_all_file_ids(db, limit=limit)

    for i, song_id in enumerate(song_ids, 1):
        rebuild_song_metadata_cache(db, song_id)
        if i % 100 == 0:
            logger.info("Rebuilt metadata cache for %d/%d songs", i, len(song_ids))

    logger.info("Completed metadata cache rebuild for %d songs", len(song_ids))
    return len(song_ids)
