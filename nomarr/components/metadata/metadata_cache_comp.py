"""Metadata cache field computation component.

Computes the forward-compatible ``metadata_cache`` member for the song
hydration intent from raw audio metadata.  Per ADR-045 the ``songs`` table
has no embedded metadata-cache columns, so these fields are never persisted —
tags are the single source of derived metadata.  The compute path is kept so
callers (notably ``tag_extraction_worker``) can still prepare the
forward-compatible input member; no cache writer remains.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Field extractors — pure functions, no DB dependency
# ---------------------------------------------------------------------------


_METADATA_CACHE_FIELDS = {
    "artist",
    "artists",
    "album",
    "labels",
    "genres",
    "year",
    "bpm",
    "key",
    "title",
    "tracknumber",
    "discnumber",
}


def compute_metadata_cache_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    """Extract embedded cache fields from raw metadata.

    Pure function — takes a metadata dict from tag parsing and returns only
    the fields that would have belonged on the (now-removed) embedded cache.
    The result is accepted by the hydration contract as a forward-compatible
    ``metadata_cache`` member but is deliberately never persisted (ADR-045).

    Args:
        metadata: Raw metadata key-value dict from tag extraction.

    Returns:
        Filtered dict with only cache-relevant fields.

    """
    result: dict[str, Any] = {}
    for key in _METADATA_CACHE_FIELDS:
        value = metadata.get(key)
        if value is not None:
            # Arrays stored as sorted lists
            if isinstance(value, (list, set)):
                sorted_str = sorted(str(v) for v in value)
                result[key] = sorted_str
            elif isinstance(value, str):
                result[key] = value
            else:
                result[key] = value
    return result
