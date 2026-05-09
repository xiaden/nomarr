"""Entity seeding component - derive entities from raw metadata tags.

Converts raw metadata strings into song tag edges via component-owned tag helpers.
Part of hybrid model: seed edges from imports, then rebuild cache.
"""

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.metadata.metadata_cache_comp import (
    compute_metadata_cache_fields,
    update_metadata_cache_batch,
)
from nomarr.components.tagging.tag_parsing_comp import parse_tag_values
from nomarr.components.tagging.tag_write_comp import set_song_tags, set_song_tags_batch

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _derive_artists(tags: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Derive singular artist and artist list from raw tag dict.

    Args:
        tags: Raw metadata tags dict (from mutagen/external source)

    Returns:
        Tuple of (primary_artist, all_artists) where primary_artist is a single
        string or None, and all_artists is a (possibly empty) list of strings.

    """
    artist_raw = tags.get("artist")
    artists_raw = tags.get("artists")
    primary_artist: str | None = None
    if artist_raw:
        primary_artist = (artist_raw[0] if artist_raw else None) if isinstance(artist_raw, list) else artist_raw
    elif artists_raw:
        primary_artist = (artists_raw[0] if artists_raw else None) if isinstance(artists_raw, list) else artists_raw
    all_artists: list[str] = []
    if artists_raw:
        all_artists = [str(a) for a in artists_raw if a] if isinstance(artists_raw, list) else [str(artists_raw)]
    elif primary_artist:
        all_artists = [primary_artist]
    return primary_artist, all_artists


def seed_song_entities_from_tags(db: "Database", song_id: str, tags: dict[str, Any]) -> None:
    """Derive song tag edges from raw imported metadata tags.

    Uses component-owned tag helpers to set tags directly from raw values.

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
    # ==================== ARTIST (singular) ====================
    primary_artist, all_artists = _derive_artists(tags)

    set_song_tags(db, song_id, "artist", [primary_artist] if primary_artist else [])

    # ==================== ARTISTS (multi) ====================
    # Use "artists" if present, else use ["artist"] if present
    set_song_tags(db, song_id, "artists", list(all_artists))

    # ==================== ALBUM (singular) ====================
    album_raw = tags.get("album")
    if album_raw:
        album_str = album_raw[0] if isinstance(album_raw, list) else album_raw
        set_song_tags(db, song_id, "album", [album_str])
    else:
        set_song_tags(db, song_id, "album", [])

    # ==================== LABEL (multi) ====================
    label_raw = tags.get("label")
    labels: list[str] = []
    if label_raw:
        if isinstance(label_raw, list):
            labels = [str(label_item) for label_item in label_raw if label_item]
        else:
            labels = [str(label_raw)]

    set_song_tags(db, song_id, "label", list(labels))

    # ==================== GENRES (multi) ====================
    genre_raw = tags.get("genre")
    genres: list[str] = []
    if genre_raw:
        genres = [str(g) for g in genre_raw if g] if isinstance(genre_raw, list) else [str(genre_raw)]

    set_song_tags(db, song_id, "genre", list(genres))

    # ==================== YEAR (singular) ====================
    year_raw = tags.get("year")
    if year_raw:
        year_int = year_raw if isinstance(year_raw, int) else int(year_raw)
        set_song_tags(db, song_id, "year", [year_int])
    else:
        set_song_tags(db, song_id, "year", [])


_ENTITY_TAG_KEYS = ("artist", "artists", "album", "label", "genre", "year")


def _extract_entity_tags(metadata: dict[str, Any]) -> dict[str, Any]:
    """Extract entity-relevant tag keys from scan metadata.

    Args:
        metadata: Raw file metadata dict (from mutagen)

    Returns:
        Dict with only the entity tag keys

    """
    return {k: metadata.get(k) for k in _ENTITY_TAG_KEYS}


def _build_song_tag_entries(song_id: str, tags: dict[str, Any]) -> list[dict[str, Any]]:
    """Build tag entries for batch-seeding from raw entity tags.

    Returns list of dicts with keys ``song_id``, ``name``, ``values``
    suitable for :func:`nomarr.components.tagging.tag_write_comp.set_song_tags_batch`.

    Mirrors the normalization logic in :func:`seed_song_entities_from_tags`
    but collects entries instead of calling the DB per-name.

    """
    entries: list[dict[str, Any]] = []

    # — artist (singular) —
    primary_artist, all_artists = _derive_artists(tags)

    entries.append({"song_id": song_id, "name": "artist", "values": [primary_artist] if primary_artist else []})

    # — artists (multi) —
    entries.append({"song_id": song_id, "name": "artists", "values": list(all_artists)})

    # — album (singular) —
    album_raw = tags.get("album")
    if album_raw:
        album_str = album_raw[0] if isinstance(album_raw, list) else album_raw
        entries.append({"song_id": song_id, "name": "album", "values": [album_str]})
    else:
        entries.append({"song_id": song_id, "name": "album", "values": []})

    # — label (multi) —
    label_raw = tags.get("label")
    labels: list[str] = []
    if label_raw:
        labels = [str(lbl) for lbl in label_raw if lbl] if isinstance(label_raw, list) else [str(label_raw)]
    entries.append({"song_id": song_id, "name": "label", "values": list(labels)})

    # — genre (multi) —
    genre_raw = tags.get("genre")
    genres: list[str] = []
    if genre_raw:
        genres = [str(g) for g in genre_raw if g] if isinstance(genre_raw, list) else [str(genre_raw)]
    entries.append({"song_id": song_id, "name": "genre", "values": list(genres)})

    # — year (singular) —
    year_raw = tags.get("year")
    if year_raw:
        year_int = year_raw if isinstance(year_raw, int) else int(year_raw)
        entries.append({"song_id": song_id, "name": "year", "values": [year_int]})
    else:
        entries.append({"song_id": song_id, "name": "year", "values": []})

    return entries


def _build_entity_tag_map(tags: dict[str, Any]) -> dict[str, list[Any]]:
    """Return canonical entity-tag values keyed by tag name.

    Uses the same normalization logic as :func:`seed_song_entities_from_tags`,
    but materialises the result as a mapping so batch scan persistence can merge
    it with the full raw tag set before writing everything in one call.
    """
    return {str(entry["name"]): list(entry["values"]) for entry in _build_song_tag_entries(song_id="", tags=tags)}


def _build_scan_tag_map(metadata: dict[str, Any]) -> dict[str, list[Any]]:
    """Build the authoritative persisted tag map for one scanned file.

    This mirrors the single-file sync workflow semantics:
    - persist all extracted source tags
    - add structured ``genre`` / ``year`` / ``track_number`` values
    - persist namespaced Nomarr tags under ``nom:`` keys
    - override entity tags with canonical normalized values so the tag graph and
      embedded metadata cache agree on artist/album/genre/year style.
    """
    all_tags = dict(metadata.get("all_tags", {}))
    nom_tags = metadata.get("nom_tags", {})

    if metadata.get("genre"):
        all_tags["genre"] = metadata["genre"]
    if metadata.get("year") is not None:
        all_tags["year"] = metadata["year"]
    if metadata.get("track_number") is not None:
        all_tags["track_number"] = metadata["track_number"]

    persisted_tags = parse_tag_values(all_tags) if all_tags else {}
    parsed_nom_tags = parse_tag_values(nom_tags) if nom_tags else {}
    for name, values in parsed_nom_tags.items():
        tag_name = name if name.startswith("nom:") else f"nom:{name}"
        persisted_tags[tag_name] = values

    entity_tags = _build_entity_tag_map(_extract_entity_tags(metadata))
    for name, values in entity_tags.items():
        if values or name in metadata:
            persisted_tags[name] = values

    return persisted_tags


def seed_entities_for_scan_batch(
    db: "Database",
    file_ids: list[str],
    metadata_by_id: dict[str, dict[str, Any]],
) -> int:
    """Persist scan-derived tags and update metadata caches for scanned files.

    Batch-optimised: collects per-file tag entries in-memory, then executes
    ``set_song_tags_batch`` once for the authoritative source-tag graph and
    ``update_metadata_cache_batch`` once for the embedded read cache.

    Despite the historical name, this step is responsible for preserving the
    full raw tag set discovered during scan, not just the entity-oriented subset.

    Args:
        db: Database instance
        file_ids: Document _ids for files that were just upserted
        metadata_by_id: Map of file_id -> raw metadata dict

    Returns:
        Number of files successfully prepared for cache updates

    """
    if not file_ids:
        return 0

    # Build all tag entries and cache updates in-memory (no DB lookups needed)
    all_tag_entries: list[dict[str, Any]] = []
    cache_updates: list[dict[str, Any]] = []

    for file_id in file_ids:
        metadata = metadata_by_id.get(file_id)

        if not metadata:
            logger.warning("No metadata for file_id: %s", file_id)
            continue

        try:
            persisted_tags = _build_scan_tag_map(metadata)
            all_tag_entries.extend(
                {"song_id": file_id, "name": name, "values": values} for name, values in persisted_tags.items()
            )
            cache_updates.append({"song_id": file_id, **compute_metadata_cache_fields(metadata)})
        except Exception as e:
            logger.warning("Failed to build entities for file_id %s: %s", file_id, e)

    # 3) Batch persist tags (3 AQL total instead of per-file writes)
    if all_tag_entries:
        try:
            set_song_tags_batch(db, all_tag_entries)
        except Exception as e:
            logger.warning("Batch tag persistence failed: %s", e)
            return 0

    # 4) Batch update metadata cache (1 AQL instead of N)
    if cache_updates:
        try:
            update_metadata_cache_batch(db, cache_updates)
        except Exception as e:
            logger.warning("Batch cache update failed: %s", e)

    return len(cache_updates)
