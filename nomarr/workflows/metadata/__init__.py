"""Metadata workflows — entity cleanup and metadata maintenance.

Provides the ``cleanup_orphaned_entities_workflow`` which detects and
removes artist/album/genre entities that no longer have any associated
song documents in the database.
"""

from .cleanup_orphaned_entities_wf import cleanup_orphaned_entities_workflow

__all__ = [
    "cleanup_orphaned_entities_workflow",
]
