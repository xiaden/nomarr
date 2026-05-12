from __future__ import annotations

from typing import Any

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase

Document = dict[str, Any]
_NO_LIMIT_COUNT = 2_147_483_647


def _extract_key(document_id_or_key: str) -> str:
    return document_id_or_key.split("/", 1)[1] if "/" in document_id_or_key else document_id_or_key


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


class TagsAqlOperations:
    """Thin Tier 2 bindings for tag documents and file↔tag traversals."""

    COLLECTION = "tags"
    EDGE_COLLECTION = "song_has_tags"
    FILE_STATE_EDGE_COLLECTION = "file_has_state"
    TAG_MODEL_OUTPUT_COLLECTION = "tag_model_output"
    ALLOWED_FIELDS = frozenset({"name", "value"})
    ALLOWED_AGGREGATE_FIELDS = frozenset({"_id", "_key", "name", "value"})

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

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

    def add_tag(self, file_id: str, payload: dict[str, Any]) -> str:
        tag_id = primitives.insert_document(self._db, self.COLLECTION, payload)
        self._upsert_tag_edge(file_id, tag_id)
        return tag_id

    def get_tag(self, tag_id: str) -> Document | None:
        results = primitives.get_many_by_keys(self._db, self.COLLECTION, [_extract_key(tag_id)])
        return results[0] if results else None

    def find_or_create_tag(self, tag_key: str, value: Any) -> str:
        cursor = self._db.aql.execute(
            """
            UPSERT { name: @tag_key, value: @value }
                INSERT { name: @tag_key, value: @value }
                UPDATE {}
                IN @@collection
                RETURN NEW._id
            """,
            bind_vars={"@collection": self.COLLECTION, "tag_key": tag_key, "value": value},
        )
        results = list(cursor)
        return str(results[0])

    def upsert_tag(self, file_id: str, tag_key: str, payload: dict[str, Any]) -> None:
        self.delete_tag(file_id, tag_key)
        merged_payload = dict(payload)
        merged_payload.setdefault("name", tag_key)
        self.add_tag(file_id, merged_payload)

    def get_tags_for_file(self, file_id: str) -> list[Document]:
        return primitives.execute(
            self._db,
            """
            FOR edge IN @@edge_collection
                FILTER edge._from == @file_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null
                SORT tag.name, tag.value
                RETURN tag
            """,
            {
                "@edge_collection": self.EDGE_COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
            },
        )

    def get_tags_for_files_batch(
        self,
        file_ids: list[str],
        *,
        name_starts_with: str | None = None,
        include_edge: bool = False,
    ) -> list[Document]:
        normalized_file_ids = [_as_document_id("library_files", file_id) for file_id in file_ids]
        if not normalized_file_ids:
            return []
        bind_vars: dict[str, Any] = {
            "@edge_collection": self.EDGE_COLLECTION,
            "file_ids": normalized_file_ids,
        }
        query_lines = [
            "FOR edge IN @@edge_collection",
            "    FILTER edge._from IN @file_ids",
            "    LET tag = DOCUMENT(edge._to)",
            "    FILTER tag != null",
        ]
        if name_starts_with is not None:
            query_lines.append("    FILTER STARTS_WITH(tag.name, @name_starts_with)")
            bind_vars["name_starts_with"] = name_starts_with
        query_lines.append("    SORT edge._from, tag.name, tag.value, tag._key")
        if include_edge:
            query_lines.append("    RETURN { start_id: edge._from, v: tag, e: edge }")
        else:
            query_lines.append("    RETURN { start_id: edge._from, v: tag }")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def list_all_tag_names(self, limit: int) -> list[str]:
        bind_vars: dict[str, Any] = {"@collection": self.COLLECTION}
        query_lines = [
            "FOR tag IN @@collection",
            "    COLLECT name = tag.name",
            "    SORT name",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN name")
        cursor = self._db.aql.execute("\n".join(query_lines), bind_vars=bind_vars)
        return [str(name) for name in cursor]

    def get_tags_by_name(self, name: str, limit: int) -> list[Document]:
        return primitives.get_many_by_field(
            self._db,
            self.COLLECTION,
            "name",
            name,
            limit=limit,
            allowed_fields=self.ALLOWED_FIELDS,
        )

    def get_genre_tags_for_files(self, file_ids: list[str]) -> list[Document]:
        normalized_file_ids = [_as_document_id("library_files", file_id) for file_id in file_ids]
        if not normalized_file_ids:
            return []
        return primitives.execute(
            self._db,
            """
            FOR edge IN @@edge_collection
                FILTER edge._from IN @file_ids
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND tag.name == "genre"
                SORT edge._from, tag.value, tag._key
                RETURN { fid: edge._from, genre: tag.value, tag_id: tag._id }
            """,
            {"@edge_collection": self.EDGE_COLLECTION, "file_ids": normalized_file_ids},
        )

    def list_tags(
        self,
        *,
        name: str | None = None,
        value: Any = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Document]:
        bind_vars: dict[str, Any] = {"@collection": self.COLLECTION, "offset": max(offset, 0)}
        query_lines = ["FOR tag IN @@collection"]
        if name is not None:
            query_lines.append("    FILTER tag.name == @name")
            bind_vars["name"] = name
        if value is not None:
            query_lines.append("    FILTER tag.value == @value")
            bind_vars["value"] = value
        query_lines.append("    SORT tag.name, tag.value, tag._key")
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @offset, @limit")
            bind_vars["limit"] = normalized_limit
        elif offset > 0:
            query_lines.append("    LIMIT @offset, @full_count")
            bind_vars["full_count"] = _NO_LIMIT_COUNT
        query_lines.append("    RETURN tag")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def count_tags(self) -> int:
        cursor = self._db.aql.execute(
            """
            FOR tag IN @@collection
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@collection": self.COLLECTION},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def aggregate_tag_field(self, field: str, *, limit: int | None = None, offset: int = 0) -> list[Document]:
        primitives._validate_field_name(field)
        if field not in self.ALLOWED_AGGREGATE_FIELDS:
            msg = f"Field {field!r} is not allowed for tag aggregation"
            raise ValueError(msg)
        bind_vars: dict[str, Any] = {"@collection": self.COLLECTION, "offset": max(offset, 0)}
        query_lines = [
            "FOR tag IN @@collection",
            f"    COLLECT value = tag.{field} WITH COUNT INTO count",
            "    SORT value",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @offset, @limit")
            bind_vars["limit"] = normalized_limit
        elif offset > 0:
            query_lines.append("    LIMIT @offset, @full_count")
            bind_vars["full_count"] = _NO_LIMIT_COUNT
        query_lines.append("    RETURN { value: value, count: count }")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def get_song_tag_edges_for_tags(self, tag_ids: list[str], *, limit: int | None = None) -> list[Document]:
        if not tag_ids:
            return []
        bind_vars: dict[str, Any] = {
            "@edge_collection": self.EDGE_COLLECTION,
            "tag_ids": tag_ids,
        }
        query_lines = [
            "FOR edge IN @@edge_collection",
            "    FILTER edge._to IN @tag_ids",
            "    SORT edge._from, edge._to, edge._key",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN edge")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def insert_song_tag_edges(self, docs: list[dict[str, Any]]) -> None:
        if not docs:
            return
        self._db.aql.execute(
            """
            FOR doc IN @docs
                INSERT doc INTO @@edge_collection
            """,
            bind_vars={"@edge_collection": self.EDGE_COLLECTION, "docs": docs},
        )

    def delete_song_tag_edge_by_id(self, edge_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.EDGE_COLLECTION, [_extract_key(edge_id)])

    def delete_tag(self, file_id: str, tag_key: str) -> None:
        self._db.aql.execute(
            """
            LET tag_ids = (
                FOR edge IN @@edge_collection
                    FILTER edge._from == @file_id
                    LET tag = DOCUMENT(edge._to)
                    FILTER tag != null AND tag.name == @tag_key
                    RETURN tag._id
            )
            FOR edge IN @@edge_collection
                FILTER edge._from == @file_id AND edge._to IN tag_ids
                REMOVE edge IN @@edge_collection
            FOR tag_id IN tag_ids
                REMOVE tag_id IN @@tag_collection
                OPTIONS { ignoreErrors: true }
            """,
            bind_vars={
                "@edge_collection": self.EDGE_COLLECTION,
                "@tag_collection": self.COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
                "tag_key": tag_key,
            },
        )

    def delete_all_tags_for_file(self, file_id: str) -> None:
        self._db.aql.execute(
            """
            LET tag_ids = (
                FOR edge IN @@edge_collection
                    FILTER edge._from == @file_id
                    RETURN edge._to
            )
            FOR edge IN @@edge_collection
                FILTER edge._from == @file_id
                REMOVE edge IN @@edge_collection
            FOR tag_id IN tag_ids
                REMOVE tag_id IN @@tag_collection
                OPTIONS { ignoreErrors: true }
            """,
            bind_vars={
                "@edge_collection": self.EDGE_COLLECTION,
                "@tag_collection": self.COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
            },
        )

    def upsert_song_tag_edge(self, song_id: str, tag_id: str) -> None:
        self._upsert_tag_edge(song_id, tag_id)

    def delete_song_tag_edges_for_file(self, file_id: str) -> None:
        self._db.aql.execute(
            """
            FOR edge IN @@edge_collection
                FILTER edge._from == @file_id
                REMOVE edge IN @@edge_collection
            """,
            bind_vars={
                "@edge_collection": self.EDGE_COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
            },
        )

    def count_song_tag_edges(self, tag_id: str) -> int:
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@edge_collection
                FILTER edge._to == @tag_id
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@edge_collection": self.EDGE_COLLECTION, "tag_id": _as_document_id(self.COLLECTION, tag_id)},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def count_song_tag_edges_for_file_state(self, file_id: str, state_tag_id: str) -> int:
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@edge_collection
                FILTER edge._from == @file_id AND edge._to == @state_id
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={
                "@edge_collection": self.FILE_STATE_EDGE_COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
                "state_id": _as_document_id("file_states", state_tag_id),
            },
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def get_orphaned_tag_ids(self) -> list[str]:
        """Return IDs of tag documents that have no song_has_tags edges and no tag_model_output edges."""
        results = primitives.execute(
            self._db,
            """
            FOR tag IN @@tag_collection
                LET song_edges = LENGTH(
                    FOR edge IN @@song_edge_collection
                        FILTER edge._to == tag._id
                        LIMIT 1
                        RETURN 1
                )
                LET model_edges = LENGTH(
                    FOR edge IN @@model_edge_collection
                        FILTER edge._from == tag._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER song_edges == 0 AND model_edges == 0
                RETURN tag._id
            """,
            {
                "@tag_collection": self.COLLECTION,
                "@song_edge_collection": self.EDGE_COLLECTION,
                "@model_edge_collection": self.TAG_MODEL_OUTPUT_COLLECTION,
            },
        )
        return [str(r) for r in results]

    def delete_tags_by_ids(self, tag_ids: list[str]) -> int:
        """Delete tag documents by their IDs. Returns the count of tags deleted."""
        if not tag_ids:
            return 0
        keys = [_extract_key(tag_id) for tag_id in tag_ids]
        return primitives.delete_many_by_keys(self._db, self.COLLECTION, keys)

    def truncate_tags(self) -> None:
        self._truncate_collection(self.COLLECTION)

    def truncate_song_tag_edges(self) -> None:
        self._truncate_collection(self.EDGE_COLLECTION)

    def _upsert_tag_edge(self, file_id: str, tag_id: str) -> None:
        self._db.aql.execute(
            """
            UPSERT { _from: @file_id, _to: @tag_id }
                INSERT { _from: @file_id, _to: @tag_id }
                UPDATE {}
                IN @@edge_collection
            """,
            bind_vars={
                "@edge_collection": self.EDGE_COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
                "tag_id": _as_document_id(self.COLLECTION, tag_id),
            },
        )

    def _truncate_collection(self, collection_name: str) -> None:
        self._db.aql.execute(
            """
            FOR doc IN @@collection
                REMOVE doc IN @@collection
            """,
            bind_vars={"@collection": collection_name},
        )
