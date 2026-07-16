"""Tag hydration component.

Derives canonical song metadata (artist, album, title, etc.) from a song's tags.
Part of the tag-first architecture: tags are the authoritative source, and
display metadata is derived on read rather than stored redundantly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def extract_canonical_metadata(song_tags: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive canonical metadata from a song's tags.

    Accepts a list of tag entries (each with a "name" and "value") and returns
    a dict of derived metadata fields suitable for display and sorting.

    Args:
        song_tags: Tag entries for one song. Each dict has "name" (tag name)
                   and "value" (list of values) fields.

    Returns:
        Dict with keys: artist, album, title, artists, labels, genres, year.
        Scalar fields (artist, album, title, year) are None when absent.
        List fields (artists, labels, genres) are None when absent.

    """
    tags_by_name = _group_tags_by_name(song_tags)

    artist_raw = [str(v) for v in tags_by_name.get("artist", [])]
    artists_raw = [str(v) for v in tags_by_name.get("artists", [])]
    album_raw = [str(v) for v in tags_by_name.get("album", [])]
    title_raw = [str(v) for v in tags_by_name.get("title", [])]
    label_raw = [str(v) for v in tags_by_name.get("label", [])]
    genre_raw = [str(v) for v in tags_by_name.get("genre", [])]
    year_raw = [str(v) for v in tags_by_name.get("year", [])]

    # artist: first of "artist" tag, fallback to first of "artists" tag
    artist = str(artist_raw[0]) if artist_raw else (str(artists_raw[0]) if artists_raw else None)
    album = str(album_raw[0]) if album_raw else None
    title = str(title_raw[0]) if title_raw else None

    artists = sorted([str(a) for a in artists_raw]) if artists_raw else None
    labels = sorted([str(lbl) for lbl in label_raw]) if label_raw else None
    genres = sorted([str(g) for g in genre_raw]) if genre_raw else None

    year = None
    if year_raw:
        try:
            year = int(year_raw[0])
        except (ValueError, TypeError):
            logger.warning("Failed to parse year from tag: %s", year_raw[0])

    return {
        "artist": artist,
        "album": album,
        "title": title,
        "artists": artists,
        "labels": labels,
        "genres": genres,
        "year": year,
    }


async def hydrate_songs_with_metadata(db: Database, songs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich songs with canonical metadata derived from their tags.

    Batch-reads tags for all songs and merges derived metadata into each.
    Returns new dicts (does not mutate input). Metadata fields are merged on top
    of original song fields, so song["artist"], song["album"], etc. resolve to
    tag-derived values.

    Args:
        db: Database instance
        songs: List of song dicts to hydrate

    Returns:
        List of new dicts with metadata fields merged in. Songs without a
        string _id are returned as shallow copies. Songs with no tags are
        returned as-is (no ``None``-valued metadata keys are injected).

    """
    song_ids = [song_id for song in songs if isinstance(song_id := song.get("id"), str)]

    if not song_ids:
        return [{**song} for song in songs]

    tags_by_song = await db.library.list_file_tags_for_files(song_ids)

    result: list[dict[str, Any]] = []
    for song in songs:
        song_id = song.get("id")

        if not isinstance(song_id, str):
            result.append({**song})
            continue

        song_tags = tags_by_song.get(song_id, [])
        metadata = extract_canonical_metadata(song_tags)
        # Strip None values so they don't override embedded cache fields
        # (e.g., artist/album stored via update_metadata_cache_batch)
        metadata = {k: v for k, v in metadata.items() if v is not None}
        result.append({**song, **metadata})

    return result


async def hydrate_song_with_metadata(db: Database, song: dict[str, Any]) -> dict[str, Any]:
    """Enrich a single song with canonical metadata derived from its tags.

    Convenience wrapper around hydrate_songs_with_metadata() for call sites
    that have exactly one song.

    Args:
        db: Database instance
        song: Single song dict to hydrate

    Returns:
        New dict with metadata fields merged in. If the song has no string _id,
        returns a shallow copy unchanged.

    """
    return hydrate_songs_with_metadata(db, [song])[0]


def _group_tags_by_name(song_tags: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """Group tag entries by name, collecting all values per name.

    Args:
        song_tags: Tag entries, each with "name" and "value" fields.

    Returns:
        Dict mapping tag name to list of all values for that name.

    """
    grouped: dict[str, list[Any]] = {}
    for tag in song_tags:
        name = tag.get("name", tag.get("key"))
        if name is None:
            continue
        value = tag.get("value", [])
        if not isinstance(value, list):
            value = [value]
        if name not in grouped:
            grouped[name] = []
        grouped[name].extend(value)
    return grouped
