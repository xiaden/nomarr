"""Metadata cache rebuild component.

Rebuilds derived song metadata fields from authoritative song_tag_edges.
Part of hybrid entity graph: edges are truth, embedded fields are read cache.
"""

import logging
from typing import Any, cast

from arango.database import StandardDatabase

from nomarr.persistence.database.song_tag_edges_aql import SongTagEdgeOperations

logger = logging.getLogger(__name__)


def rebuild_song_metadata_cache(db: StandardDatabase, song_id: str) -> None:
    """Rebuild embedded metadata cache fields on a song from edges.

    Reads entities from song_tag_edges and writes derived fields to song document.
    This is the authoritative repair mechanism for the hybrid model.

    Args:
        db: Database handle
        song_id: Song _id (e.g., "library_files/12345")
    """
    edges = SongTagEdgeOperations(db)

    # Fetch entities for each relation type
    artist_entities = edges.list_entities_for_song(song_id, "artist")
    artists_entities = edges.list_entities_for_song(song_id, "artists")
    album_entities = edges.list_entities_for_song(song_id, "album")
    label_entities = edges.list_entities_for_song(song_id, "label")
    genre_entities = edges.list_entities_for_song(song_id, "genres")
    year_entities = edges.list_entities_for_song(song_id, "year")

    # Derive embedded field values
    artist = artist_entities[0]["display_name"] if artist_entities else None
    artists = sorted([e["display_name"] for e in artists_entities]) if artists_entities else None
    album = album_entities[0]["display_name"] if album_entities else None
    labels = sorted([e["display_name"] for e in label_entities]) if label_entities else None
    genres = sorted([e["display_name"] for e in genre_entities]) if genre_entities else None

    # Year: convert display_name back to int if present
    year = None
    if year_entities:
        try:
            year = int(year_entities[0]["display_name"])
        except (ValueError, KeyError):
            logger.warning("Failed to parse year from entity: %s", year_entities[0])

    # Update song document with derived cache
    db.aql.execute(
        """
        UPDATE PARSE_IDENTIFIER(@song_id).key WITH {
            artist: @artist,
            artists: @artists,
            album: @album,
            labels: @labels,
            genres: @genres,
            year: @year
        } IN library_files
        """,
        bind_vars=cast(
            dict[str, Any],
            {
                "song_id": song_id,
                "artist": artist,
                "artists": artists,
                "album": album,
                "labels": labels,
                "genres": genres,
                "year": year,
            },
        ),
    )


def rebuild_all_song_metadata_caches(db: StandardDatabase, limit: int | None = None) -> int:
    """Rebuild metadata cache for all songs in library.

    Args:
        db: Database handle
        limit: Optional limit for testing (None = all songs)

    Returns:
        Number of songs processed
    """
    from typing import cast

    from arango.cursor import Cursor

    # Get all song _ids
    query = "FOR file IN library_files SORT file._key"
    if limit:
        query += f" LIMIT {limit}"
    query += " RETURN file._id"

    cursor = cast(Cursor, db.aql.execute(query))
    song_ids = list(cursor)

    for i, song_id in enumerate(song_ids, 1):
        rebuild_song_metadata_cache(db, song_id)
        if i % 100 == 0:
            logger.info("Rebuilt metadata cache for %d/%d songs", i, len(song_ids))

    logger.info("Completed metadata cache rebuild for %d songs", len(song_ids))
    return len(song_ids)
