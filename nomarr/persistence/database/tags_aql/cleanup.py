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
        """Delete orphaned tags and their outbound edges atomically.

        A tag is orphaned when it meets **both** conditions:
        - No ``song_has_tags`` edge references it (not attached to any file)
        - No ``tag_model_output`` edge originates from it (not linked to any
          ML model output activation)

        **Cascade:** Because ArangoDB's document-API ``REMOVE`` does not
        auto-cascade edge deletions, this query explicitly deletes all
        ``tag_model_output`` edges whose ``_from`` points to an orphaned tag
        before removing the tag vertices.  The two deletions happen inside a
        single AQL query so they are effectively transactional.

        **Intentional asymmetry:** Calibration-produced mood tags
        (``nom:mood-*``) are written only via ``song_has_tags`` edges and
        therefore become orphaned (and are removed here) as soon as their
        associated files are deleted.  Inference-produced tags may also
        carry ``tag_model_output`` edges; those edges *extend* a tag's
        lifetime beyond the point where its files are removed — the tag
        survives until the model output is itself deregistered and the
        ``tag_model_output`` edge is dropped.

        Use this periodically or after bulk file deletions.
        """
        query = """
        LET orphans = (
            FOR tag IN tags
                LET song_edges = LENGTH(
                    FOR edge IN song_has_tags
                        FILTER edge._to == tag._id
                        LIMIT 1
                        RETURN 1
                )
                LET model_edges = LENGTH(
                    FOR edge IN tag_model_output
                        FILTER edge._from == tag._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER song_edges == 0 AND model_edges == 0
                RETURN { _key: tag._key, _id: tag._id }
        )
        LET orphan_ids = orphans[*]._id
        LET _del_edges = (
            FOR edge IN tag_model_output
                FILTER edge._from IN orphan_ids
                REMOVE edge IN tag_model_output
                RETURN 1
        )
        FOR o IN orphans
            REMOVE { _key: o._key } IN tags
        RETURN LENGTH(orphans)
        """
        cursor = cast("Cursor", self.db.aql.execute(query))
        result = list(cursor)
        return result[0] if result else 0

    def get_orphaned_tag_count(self) -> int:
        """Count tags with no edges (for reporting before cleanup).

        Uses the same dual-edge condition as
        :meth:`cleanup_orphaned_tags`.
        """
        query = """
        RETURN LENGTH(
            FOR tag IN tags
                LET song_edges = LENGTH(
                    FOR edge IN song_has_tags
                        FILTER edge._to == tag._id
                        LIMIT 1
                        RETURN 1
                )
                LET model_edges = LENGTH(
                    FOR edge IN tag_model_output
                        FILTER edge._from == tag._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER song_edges == 0 AND model_edges == 0
                RETURN 1
        )
        """
        cursor = cast("Cursor", self.db.aql.execute(query))
        result = list(cursor)
        return result[0] if result else 0
