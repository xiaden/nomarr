"""Metadata cache rebuild component.

Rebuilds derived song metadata fields from authoritative tags collection.
Part of hybrid entity graph: tags are truth, embedded fields are read cache.
"""

import contextlib
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from arango.cursor import Cursor

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
            "dict[str, Any]",
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


def compute_metadata_cache_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    """Derive metadata cache fields from raw scan metadata (no DB access).

    Produces the same result as :func:`rebuild_song_metadata_cache` would
    after a full round-trip through entity seeding, but without any DB reads.
    Use this during scan to avoid the redundant read-back.

    Args:
        metadata: Raw file metadata dict (from mutagen)

    Returns:
        Dict with cache fields: artist, artists, album, labels, genres, year

    """
    # — artist / artists (same fallback logic as seed_song_entities_from_tags) —
    artist_raw = metadata.get("artist")
    artists_raw = metadata.get("artists")

    primary_artist: str | None = None
    if artist_raw:
        val = artist_raw[0] if isinstance(artist_raw, list) else artist_raw
        primary_artist = str(val) if val else None
    elif artists_raw:
        val = artists_raw[0] if isinstance(artists_raw, list) else artists_raw
        primary_artist = str(val) if val else None

    all_artists: list[str] | None = None
    if artists_raw:
        if isinstance(artists_raw, list):
            all_artists = sorted(str(a) for a in artists_raw if a)
        else:
            all_artists = [str(artists_raw)]
    elif primary_artist:
        all_artists = [primary_artist]

    # — album —
    album_raw = metadata.get("album")
    album: str | None = None
    if album_raw:
        album = str(album_raw[0]) if isinstance(album_raw, list) else str(album_raw)

    # — labels —
    label_raw = metadata.get("label")
    labels: list[str] | None = None
    if label_raw:
        if isinstance(label_raw, list):
            labels = sorted(str(lbl) for lbl in label_raw if lbl)
        else:
            labels = [str(label_raw)]

    # — genres —
    genre_raw = metadata.get("genre")
    genres: list[str] | None = None
    if genre_raw:
        if isinstance(genre_raw, list):
            genres = sorted(str(g) for g in genre_raw if g)
        else:
            genres = [str(genre_raw)]

    # — year —
    year_raw = metadata.get("year")
    year: int | None = None
    if year_raw:
        with contextlib.suppress(ValueError, TypeError):
            year = year_raw if isinstance(year_raw, int) else int(year_raw)

    return {
        "artist": primary_artist,
        "artists": all_artists or None,
        "album": album,
        "labels": labels or None,
        "genres": genres or None,
        "year": year,
    }


def update_metadata_cache_batch(db: "Database", updates: list[dict[str, Any]]) -> None:
    """Write pre-computed metadata cache fields for multiple songs in one AQL.

    Each entry in *updates* must have ``song_id`` plus the cache fields
    (artist, artists, album, labels, genres, year).

    Args:
        db: Database handle
        updates: List of dicts ``{song_id, artist, artists, album, labels, genres, year}``

    """
    if not updates:
        return

    db.db.aql.execute(
        """
        FOR entry IN @updates
            UPDATE PARSE_IDENTIFIER(entry.song_id).key WITH {
                artist: entry.artist,
                artists: entry.artists,
                album: entry.album,
                labels: entry.labels,
                genres: entry.genres,
                year: entry.year
            } IN library_files
        """,
        bind_vars=cast("dict[str, Any]", {"updates": updates}),
    )


def rebuild_all_song_metadata_caches(db: "Database", limit: int | None = None) -> int:
    """Rebuild metadata cache for all songs in library.

    Args:
        db: Database handle
        limit: Optional limit for testing (None = all songs)

    Returns:
        Number of songs processed

    """

    # Get all song _ids
    query = "FOR file IN library_files SORT file._key"
    if limit:
        query += f" LIMIT {limit}"
    query += " RETURN file._id"

    cursor = cast("Cursor", db.db.aql.execute(query))
    song_ids = list(cursor)

    for i, song_id in enumerate(song_ids, 1):
        rebuild_song_metadata_cache(db, song_id)
        if i % 100 == 0:
            logger.info("Rebuilt metadata cache for %d/%d songs", i, len(song_ids))

    logger.info("Completed metadata cache rebuild for %d songs", len(song_ids))
    return len(song_ids)
