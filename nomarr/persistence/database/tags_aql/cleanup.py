"""Cleanup operations for tags."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from arango.cursor import Cursor



logger = logging.getLogger(__name__)


class TagCleanupMixin:
    """Cleanup operations for tags."""

    db: Any
    collection: Any

    def cleanup_orphaned_tags(self) -> int:
        """Delete tags with no edges. Returns count deleted.

        Use this periodically or after bulk file deletions.
        """
        query = """
        LET orphans = (
            FOR tag IN tags
                LET edge_count = LENGTH(
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER edge_count == 0
                RETURN tag._key
        )
        FOR key IN orphans
            REMOVE { _key: key } IN tags
        RETURN LENGTH(orphans)
        """
        cursor = cast("Cursor", self.db.aql.execute(query))
        result = list(cursor)
        return result[0] if result else 0

    def get_orphaned_tag_count(self) -> int:
        """Count tags with no edges (for reporting before cleanup)."""
        query = """
        RETURN LENGTH(
            FOR tag IN tags
                LET edge_count = LENGTH(
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER edge_count == 0
                RETURN 1
        )
        """
        cursor = cast("Cursor", self.db.aql.execute(query))
        result = list(cursor)
        return result[0] if result else 0
