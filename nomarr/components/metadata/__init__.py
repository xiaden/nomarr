"""Metadata package."""

from .entity_cleanup_comp import cleanup_orphaned_tags, get_orphaned_tag_count
from .entity_seeding_comp import seed_entities_for_scan_batch, seed_song_entities_from_tags
from .metadata_cache_comp import (
    compute_metadata_cache_fields,
    rebuild_all_song_metadata_caches,
    rebuild_song_metadata_cache,
    update_metadata_cache_batch,
)

__all__ = [
    "cleanup_orphaned_tags",
    "compute_metadata_cache_fields",
    "get_orphaned_tag_count",
    "rebuild_all_song_metadata_caches",
    "rebuild_song_metadata_cache",
    "seed_entities_for_scan_batch",
    "seed_song_entities_from_tags",
    "update_metadata_cache_batch",
]
