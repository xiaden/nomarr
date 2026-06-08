"""Metadata package."""

from .entity_seeding_comp import seed_entities_for_scan_batch, seed_song_entities_from_tags

__all__ = [
    "seed_entities_for_scan_batch",
    "seed_song_entities_from_tags",
]
