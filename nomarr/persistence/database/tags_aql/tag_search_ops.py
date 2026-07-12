from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.aql import primitives

from ._helpers import _NO_LIMIT_COUNT, Document, _as_document_id

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import SafeDatabase


class TagSearchOpsMixin:
    """Mixin for tag search, listing, and counting operations.

    Requires the host class to provide ``self._db`` (a ``SafeDatabase``),
    ``self.COLLECTION``, and ``self.EDGE_COLLECTION``.
    """

    _db: SafeDatabase
    COLLECTION: str
    EDGE_COLLECTION: str

    def list_file_ids_for_tag_id(self, tag_id: str, *, limit: int | None, offset: int = 0) -> list[str]:
        bind_vars: dict[str, Any] = {
            "@edge_collection": self.EDGE_COLLECTION,
            "tag_id": _as_document_id(self.COLLECTION, tag_id),
            "offset": offset,
        }
        normalized_limit = primitives.normalize_limit(limit)
        bind_vars["limit"] = normalized_limit if normalized_limit is not None else _NO_LIMIT_COUNT
        return cast(
            "list[str]",
            primitives.execute(
                self._db,
                """
                FOR edge IN @@edge_collection
                    FILTER edge._to == @tag_id
                    SORT edge._from
                    LIMIT @offset, @limit
                    RETURN edge._from
                """,
                bind_vars,
            ),
        )

    def search_files_by_tag(self, tag_key: str, value: str, *, limit: int | None) -> list[Document]:
        bind_vars: dict[str, Any] = {
            "@tag_collection": self.COLLECTION,
            "@edge_collection": self.EDGE_COLLECTION,
            "tag_key": tag_key,
            "value": value,
        }
        query_lines = [
            "FOR tag IN @@tag_collection",
            "    FILTER tag.name == @tag_key AND tag.value == @value",
            "    FOR edge IN @@edge_collection",
            "        FILTER edge._to == tag._id",
            "        COLLECT file_id = edge._from",
            "        LET file = DOCUMENT(file_id)",
            "        FILTER file != null",
            "        SORT file._key",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("        LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("        RETURN file")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def search_files_by_tag_pattern(self, tag_name: str, pattern: str, *, limit: int | None) -> list[Document]:
        bind_vars: dict[str, Any] = {
            "@tag_collection": self.COLLECTION,
            "@edge_collection": self.EDGE_COLLECTION,
            "tag_name": tag_name,
            "pattern": pattern,
        }
        query_lines = [
            "FOR tag IN @@tag_collection",
            "    FILTER tag.name == @tag_name AND LIKE(tag.value, @pattern, true)",
            "    FOR edge IN @@edge_collection",
            "        FILTER edge._to == tag._id",
            "        COLLECT file_id = edge._from",
            "        LET file = DOCUMENT(file_id)",
            "        FILTER file != null",
            "        SORT file._key",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("        LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("        RETURN file")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def search_files_by_tag_contains(self, tag_key: str, value: str, *, limit: int | None) -> list[Document]:
        """Search for files where tag.value array contains the given value.

        Used for array-valued tags like mood tags where multiple values are stored
        in a single tag document (e.g., nom:mood-strict = ["aggressive", "happy"]).

        Args:
            tag_key: Tag name to search for (e.g., "nom:mood-strict")
            value: Value to find within the tag's value array
            limit: Maximum number of file documents to return

        Returns:
            List of file documents that have tags containing the value
        """
        bind_vars: dict[str, Any] = {
            "@tag_collection": self.COLLECTION,
            "@edge_collection": self.EDGE_COLLECTION,
            "tag_key": tag_key,
            "value": value,
        }
        query_lines = [
            "FOR tag IN @@tag_collection",
            "    FILTER tag.name == @tag_key AND @value IN tag.value",
            "    FOR edge IN @@edge_collection",
            "        FILTER edge._to == tag._id",
            "        COLLECT file_id = edge._from",
            "        LET file = DOCUMENT(file_id)",
            "        FILTER file != null",
            "        SORT file._key",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("        LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("        RETURN file")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def get_tag_value_frequencies(self, tag_name: str, *, limit: int) -> list[tuple[str, int]]:
        rows = primitives.execute(
            self._db,
            """
            FOR edge IN @@edge_collection
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND tag.name == @tag_name
                COLLECT value = tag.value WITH COUNT INTO count
                FILTER count > 0
                SORT count DESC, value
                LIMIT @limit
                RETURN { value, count }
            """,
            {
                "@edge_collection": self.EDGE_COLLECTION,
                "tag_name": tag_name,
                "limit": limit,
            },
        )
        return [
            (value, row["count"])
            for row in rows
            if isinstance((value := row.get("value")), str) and isinstance(row.get("count"), int)
        ]

    def list_all_tag_names(self, limit: int) -> list[str]:
        return cast(
            "list[str]",
            primitives.execute(
                self._db,
                """
                FOR tag IN @@tag_collection
                    COLLECT name = tag.name
                    LIMIT @limit
                    RETURN name
                """,
                {"@tag_collection": self.COLLECTION, "limit": limit},
            ),
        )

    def list_tags(
        self,
        *,
        name: str | None = None,
        value: Any = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        query_lines = ["FOR tag IN @@tag_collection"]
        bind_vars: dict[str, Any] = {"@tag_collection": self.COLLECTION}
        if name is not None:
            query_lines.append("    FILTER tag.name == @name")
            bind_vars["name"] = name
        if value is not None:
            query_lines.append("    FILTER tag.value == @value")
            bind_vars["value"] = value
        query_lines.append("    SORT tag.name, tag.value")
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @offset, @limit")
            bind_vars["offset"] = offset
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN tag")
        return cast("list[Document]", primitives.execute(self._db, "\n".join(query_lines), bind_vars))

    def count_tags(self) -> int:
        cursor = self._db.aql.execute(
            "RETURN LENGTH(@@collection)",
            bind_vars={"@collection": self.COLLECTION},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def count_tags_filtered(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
    ) -> int:
        bind_vars: dict[str, Any] = {"@collection": self.COLLECTION}
        filters: list[str] = []
        if name is not None:
            filters.append("FILTER tag.name == @name")
            bind_vars["name"] = name
        if search is not None:
            filters.append("FILTER LIKE(tag.name, @search, true)")
            bind_vars["search"] = search
        filter_clause = "\n            ".join(filters)
        cursor = self._db.aql.execute(
            f"""
            FOR tag IN @@collection
                {filter_clause}
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars=bind_vars,
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def list_tags_with_song_count(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Document]:
        bind_vars: dict[str, Any] = {
            "@edge_collection": self.EDGE_COLLECTION,
            "limit": limit,
            "offset": offset,
        }
        filter_lines: list[str] = ["    FILTER tag != null"]
        if name is not None:
            filter_lines.append("    FILTER tag.name == @name")
            bind_vars["name"] = name
        if search is not None:
            filter_lines.append("    FILTER LIKE(tag.name, @search, true)")
            bind_vars["search"] = search
        filter_clause = "\n".join(filter_lines)
        query = f"""
            FOR edge IN @@edge_collection
                LET tag = DOCUMENT(edge._to)
{filter_clause}
                COLLECT tag_id = tag._id WITH COUNT INTO song_count
                FILTER song_count > 0
                LET tag = DOCUMENT(tag_id)
                SORT song_count DESC, tag.name
                LIMIT @offset, @limit
                RETURN {{
                    _id: tag._id,
                    _key: tag._key,
                    name: tag.name,
                    value: tag.value,
                    song_count: song_count
                }}
        """
        return cast("list[Document]", primitives.execute(self._db, query, bind_vars))

    def get_tags_by_name(self, name: str, limit: int) -> list[Document]:
        return cast(
            "list[Document]",
            primitives.execute(
                self._db,
                """
                FOR tag IN @@tag_collection
                    FILTER tag.name == @name
                    LIMIT @limit
                    RETURN tag
                """,
                {"@tag_collection": self.COLLECTION, "name": name, "limit": limit},
            ),
        )
