"""
Metadata package.
"""

from .entity_keys_comp import (
    generate_album_key,
    generate_artist_key,
    generate_genre_key,
    generate_label_key,
    generate_year_key,
)
from .entity_seeding_comp import seed_song_entities_from_tags
from .metadata_cache_comp import (
    rebuild_all_song_metadata_caches,
    rebuild_song_metadata_cache,
)

__all__ = [
    "generate_album_key",
    "generate_artist_key",
    "generate_genre_key",
    "generate_label_key",
    "generate_year_key",
    "rebuild_all_song_metadata_caches",
    "rebuild_song_metadata_cache",
    "seed_song_entities_from_tags",
]
