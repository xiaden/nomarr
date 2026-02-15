"""Unified tag operations for the tags collection.

This is the ONLY canonical tag persistence implementation.
All tag read/write operations go through this module.

This is a multi-file subpackage that splits TagOperations into logical modules:
- crud.py: Basic CRUD operations (create tags, create edges)
- queries.py: General tag queries (get tags for files, search tags)
- analytics.py: Tag analytics (co-occurrence, relationships)
- cleanup.py: Tag cleanup operations (orphaned tags, etc.)
- mood.py: Mood-specific queries
- stats.py: Tag statistics

The main class TagOperations composes these mixins.

Schema:
    tags vertex collection: { _key, rel: str, value: scalar }
    song_tag_edges edge collection: { _from: library_files/_id, _to: tags/_id }

Uniqueness:
    A tag is uniquely identified by (rel, value) pair.
    Edge uniqueness enforced by unique index on [_from, _to].

Provenance Convention:
    - Nomarr-generated tags: rel starts with "nom:" (e.g., "nom:mood-strict")
    - External/user tags: all other rel values (e.g., "artist", "album", "genre")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .analytics import TagAnalyticsMixin
from .cleanup import TagCleanupMixin
from .crud import TagCrudMixin
from .mood import TagMoodMixin
from .queries import TagQueriesMixin
from .stats import TagStatsMixin

if TYPE_CHECKING:
    from arango.database import StandardDatabase

    from nomarr.persistence.arango_client import SafeDatabase


class TagOperations(
    TagCrudMixin,
    TagQueriesMixin,
    TagStatsMixin,
    TagAnalyticsMixin,
    TagMoodMixin,
    TagCleanupMixin,
):
    """Operations for the tags collection."""

    def __init__(self, db: StandardDatabase | SafeDatabase) -> None:
        self.db = db
        self.collection = db.collection("tags")


__all__ = ["TagOperations"]
