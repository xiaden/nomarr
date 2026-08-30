"""Tag hydration component.

Derives canonical song metadata (artist, album, title, etc.) from a song's tags.
Part of the tag-first architecture: tags are the authoritative source, and
display metadata is derived on read rather than stored redundantly.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def extract_canonical_metadata(song_tags: Sequence[SongTagAssignment]) -> dict[str, Any]:
    """Derive canonical metadata from a song's tag assignments.

    Args:
        song_tags: ``SongTagAssignment`` entries for one song.

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


def hydrate_songs_with_metadata(db: Database, songs: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        string/int id are returned as shallow copies. Songs that do not resolve
        to a domain song identity (or have no tags) are returned as-is (no
        ``None``-valued metadata keys are injected) — ADR-045.

    """
    song_ids: list[int] = []
    for song in songs:
        raw_id = song.get("id")
        if isinstance(raw_id, (str, int)):
            with contextlib.suppress(ValueError, TypeError):
                song_ids.append(int(raw_id))

    if not song_ids:
        return [{**song} for song in songs]

    # Batch-resolve the numeric song handles to domain identities before the
    # sealed tag call (never pass ints to the tag facade).
    identity_map = db.library.resolve_song_identities(song_ids)
    if not identity_map:
        return [{**song} for song in songs]
    id_to_identity = {identity: song_id for song_id, identity in identity_map.items()}
    tags_by_identity = db.library.list_song_tags_for_songs(list(identity_map.values()))
    tags_by_song = {song_id: tags_by_identity.get(identity, ()) for identity, song_id in id_to_identity.items()}

    result: list[dict[str, Any]] = []
    for song in songs:
        raw_id = song.get("id")
        lookup_id: int | None = None
        if isinstance(raw_id, (str, int)):
            with contextlib.suppress(ValueError, TypeError):
                lookup_id = int(raw_id)

        if lookup_id is None:
            result.append({**song})
            continue

        song_tags = tags_by_song.get(lookup_id, ())
        metadata = extract_canonical_metadata(song_tags)
        # Strip None values so they don't override tag-derived metadata
        # (ADR-045: metadata is derived from source tags, no cache columns)
        metadata = {k: v for k, v in metadata.items() if v is not None}
        result.append({**song, **metadata})

    return result


def hydrate_song_with_metadata(db: Database, song: dict[str, Any]) -> dict[str, Any]:
    """Enrich a single song with canonical metadata derived from its tags.

    Convenience wrapper around hydrate_songs_with_metadata() for call sites
    that have exactly one song.

    Args:
        db: Database instance
        song: Single song dict to hydrate

    Returns:
        New dict with metadata fields merged in. If the song has no string/int
        id, returns a shallow copy unchanged.

    """
    result = hydrate_songs_with_metadata(db, [song])
    return result[0]


def _group_tags_by_name(song_tags: Sequence[SongTagAssignment]) -> dict[str, list[Any]]:
    """Group tag assignments by name, collecting all values per name.

    Args:
        song_tags: ``SongTagAssignment`` entries for one song.

    Returns:
        Dict mapping tag name to list of all values for that name.

    """
    grouped: dict[str, list[Any]] = {}
    for tag in song_tags:
        name = tag.name
        if name is None:
            continue
        grouped.setdefault(name, []).append(tag.value)
    return grouped
