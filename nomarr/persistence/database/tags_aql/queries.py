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
            tag_specs: List of (rel, value) tuples
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

