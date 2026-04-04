"""Tag curation operations (relink edges for rename/merge/split)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dto.tag_curation_dto import RelinkResult

if TYPE_CHECKING:
    from arango.cursor import Cursor


logger = logging.getLogger(__name__)


class TagCurationMixin:
    """Mixin providing tag curation persistence primitives."""

    db: Any
    collection: Any
    cleanup_orphaned_tags: Any

    def relink_tag_edges(
        self,
        source_tag_id: str,
        target_tag_id: str,
        song_ids: list[str] | None = None,
    ) -> RelinkResult:
        """Re-link song_has_tags edges from source tag to target tag.

        Core persistence primitive for rename, merge, and split operations
        (ADR-014). Handles duplicate edges via UPSERT.

        Args:
            source_tag_id: Tag _id to move edges FROM (e.g., "tags/12345").
            target_tag_id: Tag _id to move edges TO (e.g., "tags/67890").
            song_ids: If provided, only relink edges from these songs.
                      If None, relink ALL edges from source to target.

        Returns:
            Dict with keys: moved (int), skipped (int), source_orphaned (bool).
            - moved: number of edges successfully relinked
            - skipped: number of edges that already existed on target (duplicates)
            - source_orphaned: True if source tag has zero remaining edges
              and was cleaned up

        """
        # Step 1: Get edges to relink
        if song_ids is not None:
            find_edges_query = """
            FOR edge IN song_has_tags
                FILTER edge._to == @source_tag_id
                FILTER edge._from IN @song_ids
                RETURN { _key: edge._key, _from: edge._from }
            """
            find_bind: dict[str, Any] = {
                "source_tag_id": source_tag_id,
                "song_ids": song_ids,
            }
        else:
            find_edges_query = """
            FOR edge IN song_has_tags
                FILTER edge._to == @source_tag_id
                RETURN { _key: edge._key, _from: edge._from }
            """
            find_bind = {"source_tag_id": source_tag_id}

        cursor = cast(
            "Cursor",
            self.db.aql.execute(find_edges_query, bind_vars=cast("dict[str, Any]", find_bind)),
        )
        edges_to_move = list(cursor)

        if not edges_to_move:
            return {"moved": 0, "skipped": 0, "source_orphaned": False}

        # Step 2: UPSERT new edges to target + REMOVE old edges from source
        # Uses UPSERT to handle duplicates (songs already linked to target).
        relink_query = """
        LET edges = @edges
        LET moved = (
            FOR e IN edges
                UPSERT { _from: e._from, _to: @target_tag_id }
                INSERT { _from: e._from, _to: @target_tag_id }
                UPDATE {}
                IN song_has_tags
                RETURN OLD ? 0 : 1
        )
        LET removed = (
            FOR e IN edges
                REMOVE { _key: e._key } IN song_has_tags
                RETURN 1
        )
        RETURN {
            new_edges: SUM(moved),
            removed_edges: LENGTH(removed)
        }
        """
        relink_bind: dict[str, Any] = {
            "edges": edges_to_move,
            "target_tag_id": target_tag_id,
        }
        cursor = cast(
            "Cursor",
            self.db.aql.execute(relink_query, bind_vars=cast("dict[str, Any]", relink_bind)),
        )
        result = next(iter(cursor))
        moved = int(result["new_edges"])
        skipped = len(edges_to_move) - moved

        # Step 3: Check if source tag is orphaned and clean up
        count_query = """
        RETURN LENGTH(
            FOR edge IN song_has_tags
                FILTER edge._to == @source_tag_id
                LIMIT 1
                RETURN 1
        )
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(count_query, bind_vars=cast("dict[str, Any]", {"source_tag_id": source_tag_id})),
        )
        remaining = next(iter(cursor))
        source_orphaned = remaining == 0

        if source_orphaned:
            self.cleanup_orphaned_tags()

        return {
            "moved": moved,
            "skipped": skipped,
            "source_orphaned": source_orphaned,
        }
