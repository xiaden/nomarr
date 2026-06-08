"""Tag hydration component.

Extracts canonical metadata fields from raw tag documents for library files.
Part of the tag-first architecture: tags are authoritative, embedded fields
are derived on read.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def extract_canonical_metadata(tag_docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract canonical metadata fields from raw tag documents for one file.

    Accepts raw tag documents (list of dicts with "name" and "value" fields)
    and returns a dict with derived scalar and list metadata fields.

    Mirrors derivation semantics from metadata_cache_comp.py:rebuild_song_metadata_cache()
    to ensure behavioral parity: same fallback logic for artist-from-artists,
    same int coercion for year, same sorted-list normalization.

    Args:
        tag_docs: Raw tag documents for one file. Each dict has "name" (tag name)
                  and "value" (list of values) fields.

    Returns:
        Dict with keys: artist, album, title, artists, labels, genres, year.
        Scalar fields (artist, album, title, year) are None when absent.
        List fields (artists, labels, genres) are None when absent.

    """
    # Group tag documents by key
    tags_by_key = _group_tags_by_key(tag_docs)

    # Extract raw values per key
    artist_raw = [str(v) for v in tags_by_key.get("artist", [])]
    artists_raw = [str(v) for v in tags_by_key.get("artists", [])]
    album_raw = [str(v) for v in tags_by_key.get("album", [])]
    title_raw = [str(v) for v in tags_by_key.get("title", [])]
    label_raw = [str(v) for v in tags_by_key.get("label", [])]
    genre_raw = [str(v) for v in tags_by_key.get("genre", [])]
    year_raw = [str(v) for v in tags_by_key.get("year", [])]

    # Derive scalar fields
    # artist: first of "artist" tag, fallback to first of "artists" tag
    artist = str(artist_raw[0]) if artist_raw else (str(artists_raw[0]) if artists_raw else None)
    album = str(album_raw[0]) if album_raw else None
    title = str(title_raw[0]) if title_raw else None

    # Derive list fields (sorted)
    artists = sorted([str(a) for a in artists_raw]) if artists_raw else None
    labels = sorted([str(lbl) for lbl in label_raw]) if label_raw else None
    genres = sorted([str(g) for g in genre_raw]) if genre_raw else None

    # Year: convert to int if present
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


def hydrate_file_docs_with_metadata(db: Database, file_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hydrate file docs with canonical metadata extracted from tags.

    Batch-reads tags for all file docs and merges extracted metadata into each doc.
    Returns new dicts (does not mutate input). Metadata fields are merged on top
    of original file doc fields, so doc["artist"], doc["album"], etc. resolve to
    tag-derived values.

    Args:
        db: Database instance
        file_docs: List of file documents to hydrate

    Returns:
        List of new dicts with metadata fields merged in. Files without string _id
        are returned as shallow copies. Files with no tags get None for all metadata fields.

    """
    # Extract file_ids (only those with string _id)
    file_ids = [file_id for file_doc in file_docs if isinstance(file_id := file_doc.get("_id"), str)]

    # If no valid file_ids, return copies of original docs unchanged
    if not file_ids:
        return [{**file_doc} for file_doc in file_docs]

    # Batch read all tags for all files
    raw_tags_by_file = db.library.list_file_tags_for_files(file_ids)

    # For each file_doc, extract canonical metadata and merge onto a copy
    result: list[dict[str, Any]] = []
    for file_doc in file_docs:
        file_id = file_doc.get("_id")

        # Files without string _id are returned as shallow copy
        if not isinstance(file_id, str):
            result.append({**file_doc})
            continue

        # Get tags for this file
        tag_docs = raw_tags_by_file.get(file_id, [])

        # Extract canonical metadata from tags
        metadata = extract_canonical_metadata(tag_docs)

        # Merge metadata onto copy of original doc
        hydrated_doc = {**file_doc, **metadata}
        result.append(hydrated_doc)

    return result


def hydrate_file_doc_with_metadata(db: Database, file_doc: dict[str, Any]) -> dict[str, Any]:
    """Hydrate a single file doc with canonical metadata extracted from tags.

    Convenience wrapper around hydrate_file_docs_with_metadata() for call sites
    that have exactly one file doc (e.g., get_file_by_id callers).

    Args:
        db: Database instance
        file_doc: Single file document to hydrate

    Returns:
        New dict with metadata fields merged in. If the doc has no string _id,
        returns a shallow copy unchanged.

    """
    return hydrate_file_docs_with_metadata(db, [file_doc])[0]


def _group_tags_by_key(tag_docs: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """Group raw tag documents by name, collecting all values per name.

    Args:
        tag_docs: Raw tag documents, each with "name" and "value" fields.

    Returns:
        Dict mapping tag name to list of all values for that name.

    """
    grouped: dict[str, list[Any]] = {}
    for doc in tag_docs:
        key = doc.get("name", doc.get("key"))
        if key is None:
            continue
        value = doc.get("value", [])
        # value may be a scalar or a list; normalize to list
        if not isinstance(value, list):
            value = [value]
        if key not in grouped:
            grouped[key] = []
        grouped[key].extend(value)
    return grouped
