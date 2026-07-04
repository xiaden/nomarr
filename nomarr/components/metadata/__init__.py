"""Metadata components — entity seeding from tags and entity cleanup.

Provides components for deriving artist/album/genre entities from
audio file tags and seeding them into the database, plus cleanup
operations for orphaned metadata entities.
"""

from .entity_seeding_comp import seed_entities_for_scan_batch, seed_song_entities_from_tags

__all__ = [
    "seed_entities_for_scan_batch",
    "seed_song_entities_from_tags",
]
