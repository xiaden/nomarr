"""Statistics operations for tags."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from arango.cursor import Cursor

logger = logging.getLogger(__name__)


class TagStatsMixin:
    """Statistics operations for tags."""

    db: Any
    collection: Any

    def get_unique_rels(self, nomarr_only: bool = False) -> list[str]:
        """Get all unique rel values in the tags collection.

        Args:
            nomarr_only: If True, only return rels starting with "nom:"

        Returns:
            List of unique rel strings

        """
        if nomarr_only:
            query = """
            FOR tag IN tags
                FILTER STARTS_WITH(tag.rel, "nom:")
                COLLECT rel = tag.rel
                RETURN rel
            """
        else:
            query = """
            FOR tag IN tags
                COLLECT rel = tag.rel
                RETURN rel
            """
        cursor = cast("Cursor", self.db.aql.execute(query))
        return list(cursor)

    def get_tag_value_counts(self, rel: str) -> dict[Any, int]:
        """Get value counts for a specific rel (for analytics).

        Args:
            rel: Tag key to analyze

        Returns:
            Dict of {value: song_count}

        """
        query = """
        FOR tag IN tags
            FILTER tag.rel == @rel
            LET song_count = LENGTH(
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN 1
            )
            RETURN { value: tag.value, count: song_count }
        """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"rel": rel})))
        return {row["value"]: row["count"] for row in cursor}

    def get_all_tag_stats_batched(self) -> dict[str, dict[str, Any]]:
        """Get value counts and type info for ALL tags in a single optimized query.

        Aggregates edges first (single pass), then joins with tags.
        Much faster than N subqueries.

        Returns:
            Dict of {rel: {type, is_multivalue, summary, total_count}}

        """
        # Aggregate edges by _to first (single pass over edges collection)
        # Then join with tags to get rel/value, and group by rel
        query = """
        LET edge_counts = (
            FOR edge IN song_tag_edges
                COLLECT tag_id = edge._to WITH COUNT INTO cnt
                RETURN {tag_id, cnt}
        )
        LET tag_data = (
            FOR ec IN edge_counts
                LET tag = DOCUMENT(ec.tag_id)
                FILTER tag != null
                RETURN {rel: tag.rel, value: tag.value, count: ec.cnt}
        )
        FOR td IN tag_data
            COLLECT rel = td.rel INTO entries = {value: td.value, count: td.count}
            RETURN {rel, entries}
        """
        cursor = cast("Cursor", self.db.aql.execute(query))

        result: dict[str, dict[str, Any]] = {}
        for row in cursor:
            rel = row["rel"]
            entries = row["entries"]
            values: dict[Any, int] = {e["value"]: e["count"] for e in entries}
            total_count = sum(values.values())

            # Detect type from values
            if values:
                numeric_values = [v for v in values if isinstance(v, (int, float))]
                if numeric_values and len(numeric_values) > len(values) / 2:
                    first_numeric = numeric_values[0]
                    tag_type = "float" if isinstance(first_numeric, float) else "integer"
                else:
                    tag_type = "string"
            else:
                tag_type = "unknown"

            # Generate summary
            if tag_type in ("float", "integer"):
                numeric_vals = [v for v in values if isinstance(v, (int, float))]
                if numeric_vals:
                    summary = f"min={min(numeric_vals)}, max={max(numeric_vals)}, unique={len(numeric_vals)}"
                else:
                    summary = "no values"
            else:
                summary = f"unique={len(values)}"

            result[rel] = {
                "type": tag_type,
                "is_multivalue": len(values) > 1,
                "summary": summary,
                "total_count": total_count,
            }

        return result

    def get_tag_frequencies(self, limit: int, namespace_prefix: str) -> dict[str, Any]:
        """Get tag frequency data for analytics.

        Args:
            limit: Max results per category
            namespace_prefix: Prefix to filter nomarr tags (e.g., "nom:")

        Returns:
            Dict with keys: nom_tag_rows (list of tuples), genre_rows (list of tuples)

        """
        # Count Nomarr tag rel:value combinations (rel starts with namespace_prefix)
        # Extract the key portion after the prefix for display
        query = """
        FOR tag IN tags
            FILTER STARTS_WITH(tag.rel, @prefix)
            LET song_count = LENGTH(
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN 1
            )
            FILTER song_count > 0
            LET key_part = SUBSTRING(tag.rel, LENGTH(@prefix))
            COLLECT tag_key_value = CONCAT(key_part, ':', tag.value) WITH COUNT INTO tag_count
            SORT tag_count DESC
            LIMIT @limit
            RETURN [tag_key_value, tag_count]
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"prefix": namespace_prefix, "limit": limit})),
        )
        nom_tag_rows = [tuple(row) for row in cursor]

        # Count genre tags (rel == "genre", non-Nomarr)
        query = """
        FOR tag IN tags
            FILTER tag.rel == "genre"
            LET song_count = LENGTH(
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN 1
            )
            FILTER song_count > 0
            COLLECT genre = tag.value WITH COUNT INTO count
            SORT count DESC
            LIMIT @limit
            RETURN [genre, count]
        """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"limit": limit})))
        genre_rows = [tuple(row) for row in cursor]

        return {"nom_tag_rows": nom_tag_rows, "genre_rows": genre_rows}

    def get_library_stats(self, library_id: str | None = None) -> dict[str, Any]:
        """Get aggregate library statistics for Collection Overview.

        Args:
            library_id: Optional library _id to filter by (e.g., "libraries/12345").
                        If None, returns stats for all libraries.

        Returns:
            Dict with keys: file_count, total_duration_ms, total_file_size_bytes,
                           avg_track_length_ms

        """
        filter_clause = "FILTER file.library_id == @library_id" if library_id else ""
        bind_vars: dict[str, Any] = {"library_id": library_id} if library_id else {}

        query = f"""
        FOR file IN library_files
            {filter_clause}
            COLLECT AGGREGATE
                file_count = COUNT(1),
                total_duration_s = SUM(file.duration_seconds),
                total_size = SUM(file.file_size)
            RETURN {{
                file_count: file_count,
                total_duration_ms: FLOOR((total_duration_s || 0) * 1000),
                total_file_size_bytes: total_size || 0,
                avg_track_length_ms: file_count > 0
                    ? ((total_duration_s || 0) / file_count) * 1000
                    : 0
            }}
        """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        result = next(cursor, None)
        return result or {
            "file_count": 0,
            "total_duration_ms": 0,
            "total_file_size_bytes": 0,
            "avg_track_length_ms": 0,
        }
