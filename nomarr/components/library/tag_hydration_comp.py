"""Tag hydration component.

Derives canonical song metadata (artist, album, title, etc.) from a song's tags
and returns it as the typed ``HydratedSong`` carrier. Part of the tag-first
architecture: tags are the authoritative source, and display metadata is derived
on read rather than stored redundantly (ADR-045).

The hydration boundary is fully semantic: it consumes domain ``Song`` values plus
their mutable ``SongIdentity`` locators (ADR-048) and returns ``HydratedSong``
carriers. It never reads ``songs.id``, storage rows, or raw payloads and never
merges metadata into a song document.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.song_query_types import HydratedSong

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _derive_metadata(song_tags: Sequence[SongTagAssignment]) -> Mapping[str, object]:
    """Derive the ADR-045 metadata mapping, omitting absent (None) values."""
    raw = extract_canonical_metadata(song_tags)
    return {key: value for key, value in raw.items() if value is not None}


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


def hydrate_songs_with_metadata(
    db: Database,
    songs: Sequence[Song],
    identities: Sequence[SongIdentity],
) -> list[HydratedSong]:
    """Derive ADR-045 metadata for many semantic songs and return typed carriers.

    ``songs`` and ``identities`` are parallel sequences: each ``identities[i]`` is
    the mutable locator (ADR-048) for ``songs[i]``. The owning library is never a
    row or generated id — callers hold the ``LibraryIdentity`` and pair it with the
    song's ``normalized_path``.

    Batch-reads tags for all supplied identities in one facade call. A song whose
    locator does not resolve (or which has no tags) is returned as a pass-through
    ``HydratedSong`` with an empty metadata mapping — never an error, never a
    ``None``-valued metadata injection (ADR-045), never a row leak.

    Args:
        db: Database instance.
        songs: Semantic songs to hydrate.
        identities: One ``SongIdentity`` locator per song (parallel to ``songs``).

    Returns:
        One ``HydratedSong`` per input song, in the same order. Input is never
        mutated.

    """
    if not songs:
        return []

    # Batch tag read across all locators; unresolvable/no-tag locators are absent
    # from the returned mapping and fall through to empty metadata below.
    tags_by_identity = db.library.list_song_tags_for_songs(list(identities))

    result: list[HydratedSong] = []
    for song, identity in zip(songs, identities, strict=True):
        assignments = tags_by_identity.get(identity, ())
        result.append(HydratedSong(song=song, metadata=_derive_metadata(assignments)))
    return result


def hydrate_song_with_metadata(db: Database, song: Song, identity: SongIdentity) -> HydratedSong:
    """Derive ADR-045 metadata for a single semantic song.

    Convenience wrapper around :func:`hydrate_songs_with_metadata` for call sites
    that have exactly one song and its locator.

    Args:
        db: Database instance.
        song: Semantic song to hydrate.
        identity: The song's mutable ``SongIdentity`` locator.

    Returns:
        A ``HydratedSong`` carrier. An unresolvable/no-tag song carries an empty
        metadata mapping (pass-through, never error, never ``None`` injection).

    """
    result = hydrate_songs_with_metadata(db, [song], [identity])
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
