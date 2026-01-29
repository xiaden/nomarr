"""Metadata package."""

from .entity_cleanup_comp import cleanup_orphaned_tags, get_orphaned_tag_count
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
    "cleanup_orphaned_tags",
    "generate_album_key",
    "generate_artist_key",
    "generate_genre_key",
    "generate_label_key",
    "generate_year_key",
    "get_orphaned_tag_count",
    "rebuild_all_song_metadata_caches",
    "rebuild_song_metadata_cache",
    "seed_song_entities_from_tags",
]
