"""Library ID normalization helpers.

Shared utility functions for converting between bare library keys and full
``libraries/{key}`` document ids. Kept in a leaf module so that all other
library components can import from here without creating circular dependencies.
"""

from __future__ import annotations


def normalize_library_id(library_id: str) -> str:
    """Normalize a library reference to a full ``libraries/{key}`` id."""
    if library_id.startswith("libraries/"):
        return library_id
    return f"libraries/{library_id}"


def library_key_from_ref(library_id: str) -> str:
    """Extract the library ``_key`` from either a full id or a bare key."""
    if library_id.startswith("libraries/"):
        return library_id.split("/", 1)[1]
    return library_id
