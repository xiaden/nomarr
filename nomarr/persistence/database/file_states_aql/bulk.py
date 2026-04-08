"""Batch file state transition operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

from ._constants import (
    _EDGE_COLLECTION,
    STATE_CALIBRATED,
    STATE_ERRORED,
    STATE_NOT_CALIBRATED,
    STATE_NOT_ERRORED,
    STATE_NOT_SCANNED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_SCANNED,
    STATE_TAGS_CURRENT,
    STATE_TAGS_STALE,
    STATE_VECTORS_EXTRACTED,
)

if TYPE_CHECKING:
    from arango.cursor import Cursor


class FileStatesBulkMixin:
    """Bulk transitions for the ``file_has_state`` edge graph."""

    db: DatabaseLike

    def bulk_set_not_calibrated(self) -> int:
        """Reset all ``calibrated`` files to ``not_calibrated`` and return the number of affected files."""
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR e IN @@coll
                    FILTER e._to == @calibrated
                    RETURN { key: e._key, from_id: e._from }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "calibrated": STATE_CALIBRATED,
                        "@coll": _EDGE_COLLECTION,
                    },
                ),
            ),
        )
        edges = cast("list[dict[str, str]]", list(cursor))
        if not edges:
            return 0

        keys = [edge["key"] for edge in edges]
        from_ids = [edge["from_id"] for edge in edges]

        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR k IN @keys
                REMOVE k IN @@coll
            """,
            bind_vars=cast("dict[str, Any]", {"keys": keys, "@coll": _EDGE_COLLECTION}),
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @from_ids
                INSERT { _from: fid, _to: @not_calibrated } INTO @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "from_ids": from_ids,
                    "not_calibrated": STATE_NOT_CALIBRATED,
                    "@coll": _EDGE_COLLECTION,
                },
            ),
        )
        return len(edges)

    def bulk_set_tags_stale(self, library_id: str | None = None) -> int:
        """Transition all ``tags_current`` files to ``tags_stale``, optionally restricted to one library, and return the number of affected files."""
        if library_id is not None:
            query = """
                LET lib_file_ids = (
                    FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id
                )
                FOR e IN @@coll
                    FILTER e._to == @tags_current AND e._from IN lib_file_ids
                    RETURN { key: e._key, from_id: e._from }
            """
            bind_vars: dict[str, Any] = {
                "library_id": library_id,
                "tags_current": STATE_TAGS_CURRENT,
                "@coll": _EDGE_COLLECTION,
            }
        else:
            query = """
                FOR e IN @@coll
                    FILTER e._to == @tags_current
                    RETURN { key: e._key, from_id: e._from }
            """
            bind_vars = {
                "tags_current": STATE_TAGS_CURRENT,
                "@coll": _EDGE_COLLECTION,
            }

        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                query,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        edges = cast("list[dict[str, str]]", list(cursor))
        if not edges:
            return 0

        keys = [edge["key"] for edge in edges]
        from_ids = [edge["from_id"] for edge in edges]

        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR k IN @keys
                REMOVE k IN @@coll
            """,
            bind_vars=cast("dict[str, Any]", {"keys": keys, "@coll": _EDGE_COLLECTION}),
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @from_ids
                INSERT { _from: fid, _to: @tags_stale } INTO @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "from_ids": from_ids,
                    "tags_stale": STATE_TAGS_STALE,
                    "@coll": _EDGE_COLLECTION,
                },
            ),
        )
        return len(edges)

    def bulk_set_scanned(self, file_ids: list[str]) -> int:
        """Transition the given files from ``not_scanned`` to ``scanned`` and return the number of affected files."""
        if not file_ids:
            return 0

        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR e IN @@coll
                    FILTER e._to == @not_scanned AND e._from IN @file_ids
                    RETURN { key: e._key, from_id: e._from }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "not_scanned": STATE_NOT_SCANNED,
                        "file_ids": file_ids,
                        "@coll": _EDGE_COLLECTION,
                    },
                ),
            ),
        )
        edges = cast("list[dict[str, str]]", list(cursor))
        if not edges:
            return 0

        keys = [edge["key"] for edge in edges]
        from_ids = [edge["from_id"] for edge in edges]

        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR k IN @keys
                REMOVE k IN @@coll
            """,
            bind_vars=cast("dict[str, Any]", {"keys": keys, "@coll": _EDGE_COLLECTION}),
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @from_ids
                INSERT { _from: fid, _to: @scanned } INTO @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "from_ids": from_ids,
                    "scanned": STATE_SCANNED,
                    "@coll": _EDGE_COLLECTION,
                },
            ),
        )
        return len(edges)

    def bulk_set_not_vectors_extracted(self) -> int:
        """Reset all ``vectors_extracted`` files to ``not_vectors_extracted`` and return the number of affected files."""
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR e IN @@coll
                    FILTER e._to == @vectors_extracted
                    RETURN { key: e._key, from_id: e._from }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "vectors_extracted": STATE_VECTORS_EXTRACTED,
                        "@coll": _EDGE_COLLECTION,
                    },
                ),
            ),
        )
        edges = cast("list[dict[str, str]]", list(cursor))
        if not edges:
            return 0

        keys = [edge["key"] for edge in edges]
        from_ids = [edge["from_id"] for edge in edges]

        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR k IN @keys
                REMOVE k IN @@coll
            """,
            bind_vars=cast("dict[str, Any]", {"keys": keys, "@coll": _EDGE_COLLECTION}),
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @from_ids
                INSERT { _from: fid, _to: @not_vectors_extracted } INTO @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "from_ids": from_ids,
                    "not_vectors_extracted": STATE_NOT_VECTORS_EXTRACTED,
                    "@coll": _EDGE_COLLECTION,
                },
            ),
        )
        return len(edges)

    def bulk_set_not_errored(self, file_ids: list[str]) -> int:
        """Clear the ``errored`` state for the given files and return the number of affected files."""
        if not file_ids:
            return 0

        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR e IN @@coll
                    FILTER e._to == @errored AND e._from IN @file_ids
                    RETURN { key: e._key, from_id: e._from }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "errored": STATE_ERRORED,
                        "file_ids": file_ids,
                        "@coll": _EDGE_COLLECTION,
                    },
                ),
            ),
        )
        edges = cast("list[dict[str, str]]", list(cursor))
        if not edges:
            return 0

        keys = [edge["key"] for edge in edges]
        from_ids = [edge["from_id"] for edge in edges]

        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR k IN @keys
                REMOVE k IN @@coll
            """,
            bind_vars=cast("dict[str, Any]", {"keys": keys, "@coll": _EDGE_COLLECTION}),
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @from_ids
                INSERT { _from: fid, _to: @not_errored } INTO @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "from_ids": from_ids,
                    "not_errored": STATE_NOT_ERRORED,
                    "@coll": _EDGE_COLLECTION,
                },
            ),
        )
        return len(edges)
