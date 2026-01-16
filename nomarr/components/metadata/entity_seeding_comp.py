"""Entity seeding component - derive entities from raw metadata tags.

Converts raw metadata strings into entity vertices + song_tag_edges.
Part of hybrid model: seed edges from imports, then rebuild cache.
"""

import logging
from typing import Any

from arango.database import StandardDatabase

from nomarr.helpers.entity_keys import (
    generate_album_key,
    generate_artist_key,
    generate_genre_key,
    generate_label_key,
    generate_year_key,
)
from nomarr.persistence.database.entities_aql import EntityOperations
from nomarr.persistence.database.song_tag_edges_aql import SongTagEdgeOperations

logger = logging.getLogger(__name__)


def seed_song_entities_from_tags(db: StandardDatabase, song_id: str, tags: dict[str, Any]) -> None:
    """Derive entity vertices and edges from raw imported metadata tags.

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
    entities = EntityOperations(db)
    edges = SongTagEdgeOperations(db)

    # ==================== ARTIST (singular) ====================
    artist_raw = tags.get("artist")
    artists_raw = tags.get("artists")

    # Derive singular artist: use "artist" if present, else first from "artists"
    primary_artist: str | None = None
    if artist_raw:
        if isinstance(artist_raw, list):
            primary_artist = artist_raw[0] if artist_raw else None
        else:
            primary_artist = artist_raw
    elif artists_raw:
        if isinstance(artists_raw, list):
            primary_artist = artists_raw[0] if artists_raw else None
        else:
            primary_artist = artists_raw

    if primary_artist:
        artist_key = generate_artist_key(primary_artist)
        artist_entity = entities.upsert_entity("artists", artist_key, primary_artist)
        edges.replace_song_relations(song_id, "artist", [artist_entity["_id"]])
    else:
        edges.replace_song_relations(song_id, "artist", [])

    # ==================== ARTISTS (multi) ====================
    # Use "artists" if present, else use ["artist"] if present
    all_artists: list[str] = []
    if artists_raw:
        if isinstance(artists_raw, list):
            all_artists = [str(a) for a in artists_raw if a]
        else:
            all_artists = [str(artists_raw)]
    elif primary_artist:
        all_artists = [primary_artist]

    artist_ids = []
    for artist_name in all_artists:
        artist_key = generate_artist_key(artist_name)
        artist_entity = entities.upsert_entity("artists", artist_key, artist_name)
        artist_ids.append(artist_entity["_id"])

    edges.replace_song_relations(song_id, "artists", artist_ids)

    # ==================== ALBUM (singular) ====================
    album_raw = tags.get("album")
    if album_raw and primary_artist:
        album_str = album_raw[0] if isinstance(album_raw, list) else album_raw
        album_key = generate_album_key(primary_artist, album_str)
        album_entity = entities.upsert_entity("albums", album_key, album_str)
        edges.replace_song_relations(song_id, "album", [album_entity["_id"]])
    else:
        edges.replace_song_relations(song_id, "album", [])

    # ==================== LABEL (multi) ====================
    label_raw = tags.get("label")
    labels: list[str] = []
    if label_raw:
        if isinstance(label_raw, list):
            labels = [str(l) for l in label_raw if l]
        else:
            labels = [str(label_raw)]

    label_ids = []
    for label_name in labels:
        label_key = generate_label_key(label_name)
        label_entity = entities.upsert_entity("labels", label_key, label_name)
        label_ids.append(label_entity["_id"])

    edges.replace_song_relations(song_id, "label", label_ids)

    # ==================== GENRES (multi) ====================
    genre_raw = tags.get("genre")
    genres: list[str] = []
    if genre_raw:
        if isinstance(genre_raw, list):
            genres = [str(g) for g in genre_raw if g]
        else:
            genres = [str(genre_raw)]

    genre_ids = []
    for genre_name in genres:
        genre_key = generate_genre_key(genre_name)
        genre_entity = entities.upsert_entity("genres", genre_key, genre_name)
        genre_ids.append(genre_entity["_id"])

    edges.replace_song_relations(song_id, "genres", genre_ids)

    # ==================== YEAR (singular) ====================
    year_raw = tags.get("year")
    if year_raw:
        year_int = year_raw if isinstance(year_raw, int) else int(year_raw)
        year_key = generate_year_key(year_int)
        # Store display_name as string for consistency
        year_entity = entities.upsert_entity("years", year_key, str(year_int))
        edges.replace_song_relations(song_id, "year", [year_entity["_id"]])
    else:
        edges.replace_song_relations(song_id, "year", [])
