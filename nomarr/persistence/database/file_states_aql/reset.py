"""Cleanup and reset operations for file state edges."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

from ._constants import _EDGE_COLLECTION, STATE_NOT_TAGGED, STATE_TAGGED, STATE_TAGS_NOT_WRITTEN

if TYPE_CHECKING:
    from arango.cursor import Cursor


class FileStatesResetMixin:
    """Cleanup, reset, and pending-write queries for file states."""

    db: DatabaseLike

    def clear_tagged_batch(self, file_ids: list[str]) -> int:
        """Remove ``tagged`` edges and restore ``not_tagged`` edges for many files."""
        if not file_ids:
            return 0

        bind_vars = cast(
            "dict[str, Any]",
            {
                "file_ids": file_ids,
                "tagged": STATE_TAGGED,
                "not_tagged": STATE_NOT_TAGGED,
                "@coll": _EDGE_COLLECTION,
            },
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            "FOR edge IN @@coll FILTER edge._from IN @file_ids AND edge._to == @tagged REMOVE edge IN @@coll",
            bind_vars=bind_vars,
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @file_ids
                INSERT { _from: fid, _to: @not_tagged } INTO @@coll
                OPTIONS { ignoreErrors: true }
            """,
            bind_vars=bind_vars,
        )
        return len(file_ids)

    def clear_all_states(self, file_id: str) -> int:
        """Remove all state edges for one file."""
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR edge IN @@coll
                    FILTER edge._from == @file_id
                    REMOVE edge IN @@coll
                    COLLECT WITH COUNT INTO cnt
                    RETURN cnt
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"file_id": file_id, "@coll": _EDGE_COLLECTION},
                ),
            ),
        )
        return int(next(cursor, 0))

    def clear_all_states_batch(self, file_ids: list[str]) -> int:
        """Remove all state edges for a batch of files."""
        if not file_ids:
            return 0

        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR edge IN @@coll
                    FILTER edge._from IN @file_ids
                    REMOVE edge IN @@coll
                    COLLECT WITH COUNT INTO cnt
                    RETURN cnt
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"file_ids": file_ids, "@coll": _EDGE_COLLECTION},
                ),
            ),
        )
        return int(next(cursor, 0))

    def count_pending_tag_writes(self) -> int:
        """Count files still in the ``tags_not_written`` state."""
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                RETURN LENGTH(
                    FOR f IN INBOUND @tags_not_written file_has_state
                        RETURN 1
                )
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"tags_not_written": STATE_TAGS_NOT_WRITTEN},
                ),
            ),
        )
        return int(next(cursor, 0))

    def get_pending_tag_write_file_ids(self, limit: int = 100) -> list[str]:
        """Get file IDs still waiting for tag writeback."""
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR file IN INBOUND @tags_not_written file_has_state
                    SORT file._key
                    LIMIT @limit
                    RETURN file._id
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"tags_not_written": STATE_TAGS_NOT_WRITTEN, "limit": limit},
                ),
            ),
        )
        return list(cursor)
