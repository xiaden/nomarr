"""Dynamic collection prefixes that cannot be resolved statically.

These collections are created at runtime based on discovered ML backbones
and library keys, so they are excluded from static schema extraction.
"""

DYNAMIC_COLLECTION_PREFIXES: tuple[str, ...] = (
    "vectors_track_hot__",
    "vectors_track_cold__",
)


def is_blacklisted(name: str) -> bool:
    """Check if a collection name matches a dynamic prefix."""
    return any(name.startswith(prefix) for prefix in DYNAMIC_COLLECTION_PREFIXES)
