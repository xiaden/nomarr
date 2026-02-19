"""Query operations for tags."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dto.tags_dto import Tags, TagValue

if TYPE_CHECKING:
    from arango.cursor import Cursor

logger = logging.getLogger(__name__)


class TagQueriesMixin:
    """Query operations for tags."""

    db: Any
    collection: Any
    def get_tag(self, tag_id: str) -> dict[str, Any] | None:
        """Get tag by _id. Returns {_id, _key, rel, value} or None."""
        query = """
        RETURN DOCUMENT(@tag_id)
        """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"tag_id": tag_id})))
        result = list(cursor)
        return result[0] if result and result[0] else None
    def list_tags_by_rel(
        self, rel: str, limit: int = 100, offset: int = 0, search: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all unique tag values for a rel. For browse UI.

        Args:
            rel: Tag key to filter by (e.g., "artist", "album")
            limit: Max results
            offset: Pagination offset
            search: Optional substring search on value (case-insensitive)

        Returns:
            List of {_id, _key, rel, value, song_count}

        """
        if search:
            query = """
            FOR tag IN tags
                FILTER tag.rel == @rel
                FILTER CONTAINS(LOWER(TO_STRING(tag.value)), LOWER(@search))
                SORT tag.value
                LIMIT @offset, @limit
                LET song_count = LENGTH(
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        RETURN 1
                )
                RETURN {
                    _id: tag._id,
                    _key: tag._key,
                    rel: tag.rel,
                    value: tag.value,
                    song_count: song_count
                }
            """
            bind_vars = {"rel": rel, "search": search, "limit": limit, "offset": offset}
        else:
            query = """
            FOR tag IN tags
                FILTER tag.rel == @rel
                SORT tag.value
                LIMIT @offset, @limit
                LET song_count = LENGTH(
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        RETURN 1
                )
                RETURN {
                    _id: tag._id,
                    _key: tag._key,
                    rel: tag.rel,
                    value: tag.value,
                    song_count: song_count
                }
            """
            bind_vars = {"rel": rel, "limit": limit, "offset": offset}

        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return list(cursor)
    def count_tags_by_rel(self, rel: str, search: str | None = None) -> int:
        """Count unique tags for a rel.

        Args:
            rel: Tag key to filter by
            search: Optional substring search on value

        Returns:
            Count of matching tags

        """
        if search:
            query = """
            RETURN LENGTH(
                FOR tag IN tags
                    FILTER tag.rel == @rel
                    FILTER CONTAINS(LOWER(TO_STRING(tag.value)), LOWER(@search))
                    RETURN 1
            )
            """
            bind_vars = {"rel": rel, "search": search}
        else:
            query = """
            RETURN LENGTH(
                FOR tag IN tags
                    FILTER tag.rel == @rel
                    RETURN 1
            )
            """
            bind_vars = {"rel": rel}

        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        result = list(cursor)
        return result[0] if result else 0
    def get_song_tags(self, song_id: str, rel: str | None = None, nomarr_only: bool = False) -> Tags:
        """Get all tags for a song, optionally filtered by rel or Nomarr prefix.

        Args:
            song_id: Song _id
            rel: Optional filter by specific rel (e.g., "artist")
            nomarr_only: If True, filter by STARTS_WITH(rel, "nom:")

        Returns:
            Tags collection (use .to_dict() for dict format)

        """
        if rel:
            query = """
            FOR edge IN song_tag_edges
                FILTER edge._from == @song_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND tag.rel == @rel
                RETURN { rel: tag.rel, value: tag.value }
            """
            bind_vars: dict[str, Any] = {"song_id": song_id, "rel": rel}
        elif nomarr_only:
            query = """
            FOR edge IN song_tag_edges
                FILTER edge._from == @song_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND STARTS_WITH(tag.rel, "nom:")
                RETURN { rel: tag.rel, value: tag.value }
            """
            bind_vars = {"song_id": song_id}
        else:
            query = """
            FOR edge IN song_tag_edges
                FILTER edge._from == @song_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null
                RETURN { rel: tag.rel, value: tag.value }
            """
            bind_vars = {"song_id": song_id}

        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return Tags.from_db_rows(list(cursor))

    def get_nomarr_tags_bulk(self, file_ids: list[str]) -> dict[str, Tags]:
        """Get Nomarr-namespaced tags for multiple files in a single AQL query.

        Args:
            file_ids: List of library file _ids (e.g., ["library_files/abc", ...])

        Returns:
            Dict mapping file_id -> Tags (nom: prefixed only).
            Files with no tags are absent from the result.

        """
        if not file_ids:
            return {}

        query = """
        FOR edge IN song_tag_edges
            FILTER edge._from IN @file_ids
            LET tag = DOCUMENT(edge._to)
            FILTER tag != null AND STARTS_WITH(tag.rel, "nom:")
            RETURN { file_id: edge._from, rel: tag.rel, value: tag.value }
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"file_ids": file_ids})),
        )
        rows_by_file: dict[str, list[dict[str, Any]]] = {}
        for row in cursor:
            fid = row["file_id"]
            rows_by_file.setdefault(fid, []).append({"rel": row["rel"], "value": row["value"]})

        return {fid: Tags.from_db_rows(rows) for fid, rows in rows_by_file.items()}

    def list_songs_for_tag(self, tag_id: str, limit: int = 100, offset: int = 0) -> list[str]:
        """List song _ids with this tag. For browse drill-down.

        Args:
            tag_id: Tag _id (e.g., "tags/12345")
            limit: Max results
            offset: Pagination offset

        Returns:
            List of song _ids

        """
        query = """
        FOR edge IN song_tag_edges
            FILTER edge._to == @tag_id
            SORT edge._from
            LIMIT @offset, @limit
            RETURN edge._from
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                query, bind_vars=cast("dict[str, Any]", {"tag_id": tag_id, "limit": limit, "offset": offset}),
            ),
        )
        return list(cursor)

    def get_file_ids_matching_tag(self, rel: str, operator: str, value: TagValue) -> set[str]:
        """Get file IDs matching a tag condition.

        Args:
            rel: Tag key
            operator: Comparison operator ("==", ">=", "<=", ">", "<", "CONTAINS")
            value: Value to compare

        Returns:
            Set of file _ids matching the condition

        """
        if operator == "CONTAINS":
            query = """
            FOR tag IN tags
                FILTER tag.rel == @rel
                FILTER CONTAINS(LOWER(TO_STRING(tag.value)), LOWER(@value))
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN DISTINCT edge._from
            """
        elif operator == "NOTCONTAINS":
            query = """
            FOR tag IN tags
                FILTER tag.rel == @rel
                FILTER !CONTAINS(LOWER(TO_STRING(tag.value)), LOWER(@value))
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN DISTINCT edge._from
            """
        else:
            # Build dynamic filter based on operator
            # Safe operators only - map from query syntax to AQL syntax
            safe_ops = {
                "==": "==",
                "=": "==",   # Parser uses "=" for equality
                ">=": ">=",
                "<=": "<=",
                ">": ">",
                "<": "<",
                "!=": "!=",
            }
            op = safe_ops.get(operator, "==")
            query = f"""
            FOR tag IN tags
                FILTER tag.rel == @rel
                FILTER tag.value {op} @value
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN DISTINCT edge._from
            """

        cursor = cast(
            "Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"rel": rel, "value": value})),
        )
        return set(cursor)
    def get_file_ids_for_tags(
        self, tag_specs: list[tuple[str, str]], library_id: str | None = None,
    ) -> dict[tuple[str, str], set[str]]:
        """Get file IDs for tag co-occurrence analysis.

        Args:
            tag_specs: List of (rel, value) tuples. Use value="*" to match any value for the key.
            library_id: Optional library _id to filter by.

        Returns:
            Dict mapping (rel, value) -> set of file_ids

        """
        result: dict[tuple[str, str], set[str]] = {}

        library_filter = ""
        bind_vars_base: dict[str, Any] = {}
        if library_id:
            library_filter = """
                LET file = DOCUMENT(edge._from)
                FILTER file != null AND file.library_id == @library_id
            """
            bind_vars_base["library_id"] = library_id

        for rel, value in tag_specs:
            # Support wildcard: value="*" means match any value for this key
            if value == "*":
                bind_vars = {**bind_vars_base, "rel": rel}
                query = f"""
                FOR tag IN tags
                    FILTER tag.rel == @rel
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        {library_filter}
                        RETURN edge._from
                """
            else:
                bind_vars = {**bind_vars_base, "rel": rel, "value": value}
                query = f"""
                FOR tag IN tags
                    FILTER tag.rel == @rel AND tag.value == @value
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        {library_filter}
                        RETURN edge._from
                """
            cursor = cast(
                "Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),
            )
            result[(rel, value)] = set(cursor)

        return result

    def get_file_ids_for_mood_tags(
        self, mood_values: list[str], mood_tier: str = "mood-strict", library_id: str | None = None,
    ) -> dict[str, set[str]]:
        """Get file IDs for mood tag co-occurrence with CONTAINS matching.

        Handles legacy tuple string values like "('aggressive', 'party-like')" by
        using CONTAINS to match individual mood terms within the compound string.

        Args:
            mood_values: List of individual mood terms to search for (e.g., ["aggressive", "happy"])
            mood_tier: Mood tier key suffix ("mood-strict", "mood-regular", "mood-loose")
            library_id: Optional library _id to filter by.

        Returns:
            Dict mapping mood_value -> set of file_ids that contain that mood

        """
        result: dict[str, set[str]] = {}
        rel = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier

        library_filter = ""
        bind_vars_base: dict[str, Any] = {"rel": rel}
        if library_id:
            library_filter = """
                LET file = DOCUMENT(edge._from)
                FILTER file != null AND file.library_id == @library_id
            """
            bind_vars_base["library_id"] = library_id

        for mood_value in mood_values:
            # Use CONTAINS to match mood terms within tuple strings
            # e.g., CONTAINS("('aggressive', 'party-like')", "'aggressive'") == true
            # We search for the quoted version to avoid partial matches
            search_pattern = f"'{mood_value}'"
            bind_vars = {**bind_vars_base, "search_pattern": search_pattern}
            query = f"""
            FOR tag IN tags
                FILTER tag.rel == @rel AND CONTAINS(tag.value, @search_pattern)
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    {library_filter}
                    RETURN edge._from
            """
            cursor = cast(
                "Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),
            )
            result[mood_value] = set(cursor)

        return result

    def get_unique_mood_values(
        self, mood_tier: str = "mood-strict", limit: int = 100,
    ) -> list[str]:
        """Extract unique individual mood values from tuple string tags.

        Parses tuple strings like "('aggressive', 'party-like')" and extracts
        individual mood terms, deduplicating across all files.

        Args:
            mood_tier: Mood tier suffix ("mood-strict", "mood-regular", "mood-loose")
            limit: Maximum number of unique values to return

        Returns:
            Sorted list of unique mood values

        """
        import ast

        rel = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier
        query = """
        FOR tag IN tags
            FILTER tag.rel == @rel
            RETURN DISTINCT tag.value
        """
        cursor = cast(
            "Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"rel": rel})),
        )

        # Parse each tuple string and extract individual values
        unique_values: set[str] = set()
        for value in cursor:
            if not isinstance(value, str):
                continue
            # Try to parse as Python tuple
            if value.startswith("(") and value.endswith(")"):
                try:
                    parsed = ast.literal_eval(value)
                    if isinstance(parsed, tuple):
                        unique_values.update(str(v) for v in parsed)
                        continue
                except (ValueError, SyntaxError):
                    pass
            # Try to parse as JSON array
            if value.startswith("[") and value.endswith("]"):
                try:
                    import json
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        unique_values.update(str(v) for v in parsed)
                        continue
                except json.JSONDecodeError:
                    pass
            # Single value
            unique_values.add(value)

        # Sort and limit
        return sorted(unique_values)[:limit]

