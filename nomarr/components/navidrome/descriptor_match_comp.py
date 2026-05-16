"""Resolve portable track descriptors against Nomarr library metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict, cast

from nomarr.components.library.library_file_query_comp import get_files_by_ids_with_tags
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
    return TrackDescriptor(
        title=str(file_doc.get("title") or ""),
        artist=str(file_doc.get("artist") or ""),
        album=str(file_doc.get("album") or ""),
        album_artist=str(_tag_value(file_doc, "album_artist", "albumartist") or ""),
        duration_ms=_duration_ms(file_doc),
        track_number=_tag_int(file_doc, "track_number", "tracknumber"),
        disc_number=_tag_int(file_doc, "disc_number", "discnumber"),
        year=int(file_doc["year"]) if isinstance(file_doc.get("year"), int) else None,
        nomarr_file_key=str(file_doc.get("_key") or "") or None,
    )


def _normalize_title(value: str) -> str:
    return normalize_title(value) if value else ""


def build_track_descriptor(file_doc: dict[str, Any]) -> TrackDescriptor:
    """Build a portable descriptor from hydrated ``library_files`` metadata."""
    return _descriptor_from_doc(file_doc)


def _search_candidate_docs(db: Database, field_name: str, value: str) -> list[dict[str, Any]]:
    docs = db.library.search_files_by_text(field_name, value, limit=None)
    if isinstance(docs, list):
        return cast("list[dict[str, Any]]", docs)
    return cast("list[dict[str, Any]]", db.library.list_files(filters={field_name: value}, limit=None))


def _candidate_file_ids(db: Database, seed: TrackDescriptor) -> set[str]:
    title = seed.get("title", "")
    if title:
        title_docs = _search_candidate_docs(db, "title", title)
        return {file_id for doc in title_docs if isinstance((file_id := doc.get("_id")), str)}

    artist = seed.get("artist", "")
    if artist:
        artist_docs = cast("list[dict[str, Any]]", db.library.search_files_by_tag("artist", artist, limit=None))
        return {file_id for doc in artist_docs if isinstance((file_id := doc.get("_id")), str)}

    return set()


def resolve_seed_descriptor_to_file(db: Database, seed: TrackDescriptor) -> tuple[str | None, str]:
    """Resolve a portable seed descriptor to one Nomarr ``library_files/_id``."""
    candidate_ids = _candidate_file_ids(db, seed)
    if not candidate_ids:
        return None, "descriptor_unresolved"

    docs = get_files_by_ids_with_tags(db, sorted(candidate_ids))
    descriptors_by_id = {
        file_id: _descriptor_from_doc(file_doc)
        for file_doc in docs
        if isinstance((file_id := file_doc.get("_id")), str)
    }

    title = _normalize_title(seed.get("title", ""))
    artist = normalize_artist(seed.get("artist", "")) if seed.get("artist") else ""
    album = _normalize_title(seed.get("album", ""))
    album_artist = normalize_artist(seed.get("album_artist", "")) if seed.get("album_artist") else ""

    step2_matches = [
        file_id
        for file_id, descriptor in descriptors_by_id.items()
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
        file_id
        for file_id, descriptor in descriptors_by_id.items()
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
        file_id
        for file_id, descriptor in descriptors_by_id.items()
        if _normalize_title(descriptor["title"]) == title
        and normalize_artist(descriptor["artist"]) == artist
        and _duration_close(descriptor.get("duration_ms"), seed.get("duration_ms"))
    ]
    if len(step4_matches) == 1:
        return step4_matches[0], ""
    if len(step4_matches) > 1:
        return None, "descriptor_ambiguous"

    fallback_matches = [
        file_id
        for file_id, descriptor in descriptors_by_id.items()
        if _normalize_title(descriptor["title"]) == title and normalize_artist(descriptor["artist"]) == artist
    ]
    if len(fallback_matches) == 1:
        return fallback_matches[0], ""
    if len(fallback_matches) > 1:
        return None, "descriptor_ambiguous"
    return None, "descriptor_unresolved"
