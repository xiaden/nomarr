"""Resolve portable track descriptors against Nomarr library metadata.

Descriptors are built from F's ID-free typed carriers (``TaggedSong``) and a
UUID-bearing ``SongIdentity`` locator. The ``nomarr_file_key`` field is the opaque
``nom1`` SongLocator token — never a generated ``songs.id``/``file_id``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from nomarr.components.library.library_song_query_comp import (
    locators_for_carriers,
    tagged_songs_for_locators,
)
from nomarr.components.library.song_query_types import TaggedSong, TrackSong
from nomarr.components.playlist_import.metadata_normalizer_comp import normalize_artist, normalize_title
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.song_locator_codec import encode_song_locator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dto.library_dto import FileTag
    from nomarr.persistence.db import Database


class TrackDescriptor(TypedDict):
    """Portable track descriptor exchanged between plugin and Nomarr."""

    title: str
    artist: str
    album: str
    album_artist: str
    duration_ms: int | None
    track_number: int | None
    disc_number: int | None
    year: int | None
    nomarr_file_key: str | None


def _tag_map(tags: Sequence[FileTag]) -> dict[str, str]:
    return {tag.key.casefold(): tag.value for tag in tags}


def _int_from(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else None


def _duration_ms(duration_seconds: object) -> int | None:
    if isinstance(duration_seconds, (int, float)) and not isinstance(duration_seconds, bool):
        return int(float(duration_seconds) * 1000.0)
    return None


def _duration_close(lhs_ms: int | None, rhs_ms: int | None, tolerance_ms: int = 2000) -> bool:
    if lhs_ms is None or rhs_ms is None:
        return False
    return abs(lhs_ms - rhs_ms) <= tolerance_ms


def _normalize_title(value: str) -> str:
    return normalize_title(value) if value else ""


def _descriptor_from_carrier(carrier: TaggedSong, locator: SongIdentity) -> TrackDescriptor:
    """Project an ID-free typed carrier + locator into a portable descriptor."""
    tags = _tag_map(carrier.tags)
    metadata = carrier.metadata

    def meta_str(key: str) -> str:
        value = metadata.get(key)
        return str(value) if value is not None else ""

    return TrackDescriptor(
        title=tags.get("title") or meta_str("title"),
        artist=tags.get("artist") or meta_str("artist"),
        album=tags.get("album") or meta_str("album"),
        album_artist=tags.get("album_artist") or tags.get("albumartist") or meta_str("artist"),
        duration_ms=_duration_ms(carrier.song.duration_seconds),
        track_number=_int_from(tags.get("track_number") or tags.get("tracknumber")),
        disc_number=_int_from(tags.get("disc_number") or tags.get("discnumber")),
        year=_int_from(tags.get("year") or metadata.get("year")),
        nomarr_file_key=encode_song_locator(locator),
    )


def build_track_descriptor(carrier: TaggedSong, locator: SongIdentity) -> TrackDescriptor:
    """Build a portable descriptor from an ID-free typed carrier and its locator."""
    return _descriptor_from_carrier(carrier, locator)


def _candidate_locators(db: Database, seed: TrackDescriptor) -> list[SongIdentity]:
    """Locate candidate songs by title pattern or artist tag and resolve locators."""
    title = seed.get("title", "")
    if title:
        songs = list(db.library.find_songs_with_tag_pattern("title", title, limit=None))
    elif seed.get("artist", ""):
        songs = list(db.library.find_songs_with_tag(TagRef(name="artist", value=seed["artist"]), limit=None))
    else:
        return []
    carriers = [TrackSong(song=song, metadata={}, isrc=None) for song in songs]
    return [locator for locator in locators_for_carriers(db, carriers) if locator is not None]


def _carrier_for_locator(db: Database, locator: SongIdentity) -> TaggedSong | None:
    """Build an ID-free typed carrier for one locator via the authoritative facade."""
    carriers = tagged_songs_for_locators(db, [locator])
    return carriers[0] if carriers else None


def descriptor_for_locator(db: Database, locator: SongIdentity) -> TrackDescriptor | None:
    """Build a portable descriptor for one locator, or ``None`` when absent."""
    carrier = _carrier_for_locator(db, locator)
    if carrier is None:
        return None
    return _descriptor_from_carrier(carrier, locator)


def _descriptors_by_key(db: Database, locators: Sequence[SongIdentity]) -> dict[str, TrackDescriptor]:
    """Build descriptors keyed by the opaque locator token for each candidate."""
    descriptors: dict[str, TrackDescriptor] = {}
    for locator in locators:
        carrier = _carrier_for_locator(db, locator)
        if carrier is None:
            continue
        descriptors[encode_song_locator(locator)] = _descriptor_from_carrier(carrier, locator)
    return descriptors


def resolve_seed_descriptor_to_file(db: Database, seed: TrackDescriptor) -> tuple[str | None, str]:
    """Resolve a portable seed descriptor to one opaque Nomarr locator token."""
    candidate_locators = _candidate_locators(db, seed)
    if not candidate_locators:
        return None, "descriptor_unresolved"

    descriptors_by_key = _descriptors_by_key(db, candidate_locators)

    title = _normalize_title(seed.get("title", ""))
    artist = normalize_artist(seed.get("artist", "")) if seed.get("artist") else ""
    album = _normalize_title(seed.get("album", ""))
    album_artist = normalize_artist(seed.get("album_artist", "")) if seed.get("album_artist") else ""

    step2_matches = [
        key
        for key, descriptor in descriptors_by_key.items()
        if _normalize_title(descriptor["title"]) == title
        and normalize_artist(descriptor["artist"]) == artist
        and _normalize_title(descriptor["album"]) == album
        and _duration_close(descriptor.get("duration_ms"), seed.get("duration_ms"))
    ]
    if len(step2_matches) == 1:
        return step2_matches[0], ""
    if len(step2_matches) > 1:
        return None, "descriptor_ambiguous"

    step3_matches = [
        key
        for key, descriptor in descriptors_by_key.items()
        if _normalize_title(descriptor["title"]) == title
        and _normalize_title(descriptor["album"]) == album
        and normalize_artist(descriptor.get("album_artist", "")) == album_artist
        and descriptor.get("track_number") == seed.get("track_number")
        and descriptor.get("disc_number") == seed.get("disc_number")
    ]
    if len(step3_matches) == 1:
        return step3_matches[0], ""
    if len(step3_matches) > 1:
        return None, "descriptor_ambiguous"

    step4_matches = [
        key
        for key, descriptor in descriptors_by_key.items()
        if _normalize_title(descriptor["title"]) == title
        and normalize_artist(descriptor["artist"]) == artist
        and _duration_close(descriptor.get("duration_ms"), seed.get("duration_ms"))
    ]
    if len(step4_matches) == 1:
        return step4_matches[0], ""
    if len(step4_matches) > 1:
        return None, "descriptor_ambiguous"

    fallback_matches = [
        key
        for key, descriptor in descriptors_by_key.items()
        if _normalize_title(descriptor["title"]) == title and normalize_artist(descriptor["artist"]) == artist
    ]
    if len(fallback_matches) == 1:
        return fallback_matches[0], ""
    if len(fallback_matches) > 1:
        return None, "descriptor_ambiguous"
    return None, "descriptor_unresolved"
