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
