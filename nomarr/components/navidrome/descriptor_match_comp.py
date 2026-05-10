"""Resolve portable track descriptors against Nomarr library metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict, cast

from nomarr.components.library.library_file_query_comp import get_files_by_ids_with_tags, get_tracks_for_matching
from nomarr.components.playlist_import.metadata_normalizer_comp import normalize_artist, normalize_title

if TYPE_CHECKING:
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
    musicbrainz_track_id: str | None
    musicbrainz_recording_id: str | None
    nomarr_file_key: str | None


def _tag_value(file_doc: dict[str, Any], *keys: str) -> str | None:
    key_set = {key.casefold() for key in keys}
    for tag in cast("list[dict[str, Any]]", file_doc.get("tags", [])):
        key = tag.get("key")
        value = tag.get("value")
        if isinstance(key, str) and isinstance(value, str) and key.casefold() in key_set:
            return value
    return None


def _tag_int(file_doc: dict[str, Any], *keys: str) -> int | None:
    value = _tag_value(file_doc, *keys)
    if value is None:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def _duration_ms(file_doc: dict[str, Any]) -> int | None:
    duration_seconds = file_doc.get("duration_seconds")
    if not isinstance(duration_seconds, (int, float)):
        return None
    return int(float(duration_seconds) * 1000.0)


def _duration_close(lhs_ms: int | None, rhs_ms: int | None, tolerance_ms: int = 2000) -> bool:
    if lhs_ms is None or rhs_ms is None:
        return False
    return abs(lhs_ms - rhs_ms) <= tolerance_ms


def _descriptor_from_doc(file_doc: dict[str, Any]) -> TrackDescriptor:
    musicbrainz_track_id = _tag_value(
        file_doc,
        "musicbrainz_trackid",
        "musicbrainz_track_id",
        "musicbrainz/release track id",
    )
    musicbrainz_recording_id = _tag_value(
        file_doc,
        "musicbrainz_recordingid",
        "musicbrainz_recording_id",
        "musicbrainzid",
        "musicbrainz_id",
    )
    return TrackDescriptor(
        title=str(file_doc.get("title") or ""),
        artist=str(file_doc.get("artist") or ""),
        album=str(file_doc.get("album") or ""),
        album_artist=str(_tag_value(file_doc, "album_artist", "albumartist") or ""),
        duration_ms=_duration_ms(file_doc),
        track_number=_tag_int(file_doc, "track_number", "tracknumber"),
        disc_number=_tag_int(file_doc, "disc_number", "discnumber"),
        year=int(file_doc["year"]) if isinstance(file_doc.get("year"), int) else None,
        musicbrainz_track_id=musicbrainz_track_id,
        musicbrainz_recording_id=musicbrainz_recording_id,
        nomarr_file_key=str(file_doc.get("_key") or "") or None,
    )


def _normalized(value: str) -> str:
    return normalize_title(value) if value else ""


def resolve_seed_descriptor_to_file(db: Database, seed: TrackDescriptor) -> str | None:
    """Resolve a portable seed descriptor to one Nomarr ``library_files/_id``."""
    rows = get_tracks_for_matching(db)
    file_ids = [row["_id"] for row in rows if isinstance(row.get("_id"), str)]
    docs = get_files_by_ids_with_tags(db, file_ids)
    descriptors_by_id = {
        file_id: _descriptor_from_doc(file_doc)
        for file_doc in docs
        if isinstance((file_id := file_doc.get("_id")), str)
    }

    mb_track = (seed.get("musicbrainz_track_id") or "").casefold()
    mb_recording = (seed.get("musicbrainz_recording_id") or "").casefold()
    if mb_track or mb_recording:
        mb_matches = [
            file_id
            for file_id, descriptor in descriptors_by_id.items()
            if (mb_track and (descriptor.get("musicbrainz_track_id") or "").casefold() == mb_track)
            or (mb_recording and (descriptor.get("musicbrainz_recording_id") or "").casefold() == mb_recording)
        ]
        if len(mb_matches) == 1:
            return mb_matches[0]
        if len(mb_matches) > 1:
            return None

    title = _normalized(seed.get("title", ""))
    artist = normalize_artist(seed.get("artist", "")) if seed.get("artist") else ""
    album = _normalized(seed.get("album", ""))
    album_artist = normalize_artist(seed.get("album_artist", "")) if seed.get("album_artist") else ""

    step2_matches = [
        file_id
        for file_id, descriptor in descriptors_by_id.items()
        if _normalized(descriptor["title"]) == title
        and normalize_artist(descriptor["artist"]) == artist
        and _normalized(descriptor["album"]) == album
        and _duration_close(descriptor.get("duration_ms"), seed.get("duration_ms"))
    ]
    if len(step2_matches) == 1:
        return step2_matches[0]
    if len(step2_matches) > 1:
        return None

    step3_matches = [
        file_id
        for file_id, descriptor in descriptors_by_id.items()
        if _normalized(descriptor["title"]) == title
        and _normalized(descriptor["album"]) == album
        and normalize_artist(descriptor.get("album_artist", "")) == album_artist
        and descriptor.get("track_number") == seed.get("track_number")
        and descriptor.get("disc_number") == seed.get("disc_number")
    ]
    if len(step3_matches) == 1:
        return step3_matches[0]
    if len(step3_matches) > 1:
        return None

    step4_matches = [
        file_id
        for file_id, descriptor in descriptors_by_id.items()
        if _normalized(descriptor["title"]) == title
        and normalize_artist(descriptor["artist"]) == artist
        and _duration_close(descriptor.get("duration_ms"), seed.get("duration_ms"))
    ]
    if len(step4_matches) == 1:
        return step4_matches[0]
    if len(step4_matches) > 1:
        return None

    fallback_matches = [
        file_id
        for file_id, descriptor in descriptors_by_id.items()
        if _normalized(descriptor["title"]) == title and normalize_artist(descriptor["artist"]) == artist
    ]
    if len(fallback_matches) == 1:
        return fallback_matches[0]
    return None

