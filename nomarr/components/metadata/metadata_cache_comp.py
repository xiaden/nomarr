"""Metadata cache rebuild component.

Rebuilds derived song metadata fields from authoritative tags collection.
Part of hybrid entity graph: tags are truth, embedded fields are read cache.
"""

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def rebuild_song_metadata_cache(db: "Database", song_id: str) -> None:
    """Rebuild embedded metadata cache fields on a song from tags.

    Reads tags from tags collection and writes derived fields to song document.
    This is the authoritative repair mechanism for the hybrid model.

    Args:
        db: Database handle
        song_id: Song _id (e.g., "library_files/12345")
    """
    # Fetch all tags for this song as a dict
    tags_dict = db.tags.get_song_tags(song_id).to_dict()

    # Extract metadata from tags (using rel names directly)
    artists_raw: list[str] = list(tags_dict.get("artists", []))
    artist_raw: list[str] = list(tags_dict.get("artist", []))
    album_raw: list[str] = list(tags_dict.get("album", []))
    label_raw: list[str] = list(tags_dict.get("label", []))
    genre_raw: list[str] = list(tags_dict.get("genre", []))
    year_raw: list[str] = list(tags_dict.get("year", []))

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

    # Update song document with derived cache
    db.db.aql.execute(
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


def rebuild_all_song_metadata_caches(db: "Database", limit: int | None = None) -> int:
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

    cursor = cast(Cursor, db.db.aql.execute(query))
    song_ids = list(cursor)

    for i, song_id in enumerate(song_ids, 1):
        rebuild_song_metadata_cache(db, song_id)
        if i % 100 == 0:
            logger.info("Rebuilt metadata cache for %d/%d songs", i, len(song_ids))

    logger.info("Completed metadata cache rebuild for %d songs", len(song_ids))
    return len(song_ids)
