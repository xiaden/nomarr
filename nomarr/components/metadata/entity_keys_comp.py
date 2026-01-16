"""Metadata entity key generation component.

Deterministic hash-based _key generation for entity collections.
NO normalization for equivalence - exact strings produce different entities.

This component provides domain-specific key generation logic for the
hybrid metadata entity graph (artists, albums, labels, genres, years).
"""

import hashlib


def generate_artist_key(artist: str) -> str:
    """Generate deterministic _key for artist entity.

    Args:
        artist: Exact artist name (no normalization)

    Returns:
        Entity _key (e.g., "v1_abc123...")
    """
    hash_hex = hashlib.sha256(artist.encode("utf-8")).hexdigest()[:32]
    return f"v1_{hash_hex}"


def generate_album_key(primary_artist: str, album: str) -> str:
    """Generate deterministic _key for album entity (scoped by artist).

    Args:
        primary_artist: Primary credited artist
        album: Album name

    Returns:
        Entity _key (e.g., "v1_abc123...")
    """
    combined = f"{primary_artist}\n{album}"
    hash_hex = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:32]
    return f"v1_{hash_hex}"


def generate_genre_key(genre: str) -> str:
    """Generate deterministic _key for genre entity.

    Args:
        genre: Exact genre name (no normalization)

    Returns:
        Entity _key (e.g., "v1_abc123...")
    """
    hash_hex = hashlib.sha256(genre.encode("utf-8")).hexdigest()[:32]
    return f"v1_{hash_hex}"


def generate_label_key(label: str) -> str:
    """Generate deterministic _key for label entity.

    Args:
        label: Exact label name (no normalization)

    Returns:
        Entity _key (e.g., "v1_abc123...")
    """
    hash_hex = hashlib.sha256(label.encode("utf-8")).hexdigest()[:32]
    return f"v1_{hash_hex}"


def generate_year_key(year: int) -> str:
    """Generate deterministic _key for year entity.

    Args:
        year: Year value

    Returns:
        Entity _key (e.g., "v1_abc123...")
    """
    hash_hex = hashlib.sha256(str(year).encode("utf-8")).hexdigest()[:32]
    return f"v1_{hash_hex}"
