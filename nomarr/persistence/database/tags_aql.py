from __future__ import annotations

from typing import Any, cast

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
    ALLOWED_FIELDS = frozenset({"name", "value"})
    ALLOWED_AGGREGATE_FIELDS = frozenset({"_id", "_key", "name", "value"})

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

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

    def get_tag_value_frequencies(self, tag_name: str, *, limit: int) -> list[tuple[str, int]]:
        rows = primitives.execute(
            self._db,
            """
            FOR tag IN @@tag_collection
                FILTER tag.name == @tag_name
                LET file_count = LENGTH(
                    FOR edge IN @@edge_collection
                        FILTER edge._to == tag._id
                        RETURN 1
                )
                FILTER file_count > 0
                SORT file_count DESC, tag.value
                LIMIT @limit
                RETURN { value: tag.value, count: file_count }
            """,
            {
                "@tag_collection": self.COLLECTION,
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

    def get_tag(self, tag_id: str) -> Document | None:
        results = primitives.get_many_by_keys(self._db, self.COLLECTION, [_extract_key(tag_id)])
        return results[0] if results else None

    def replace_file_tags(self, file_id: str, tags: list[dict[str, Any]]) -> None:
        """Replace all tag edges for a file and prune any orphaned tag documents.

        Args:
            file_id: File document ID whose tag associations should be replaced.
            tags: Tag payloads to attach to the file. Each payload must include a
                non-empty ``name`` or ``key`` and a ``value``.

        Raises:
            ValueError: If a payload does not include a valid tag name/key or a
                ``value`` field.
        """
        self._delete_song_tag_edges_for_file(file_id)
        if not tags:
            self._cleanup_orphaned_tags()
            return

        seen_edges: set[tuple[str, str]] = set()
        for payload in tags:
            tag_name = payload.get("name", payload.get("key"))
            if not isinstance(tag_name, str) or not tag_name:
                msg = "Tag payload must include a non-empty 'name' or 'key'"
                raise ValueError(msg)
            if "value" not in payload:
                msg = f"Tag payload for {tag_name!r} must include 'value'"
                raise ValueError(msg)
            tag_id = self._find_or_create_tag(tag_name, payload["value"])
            edge_key = (file_id, tag_id)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            self._upsert_tag_edge(file_id, tag_id)

        self._cleanup_orphaned_tags()

    def replace_tag_references(
        self,
        source_tag_id: str,
        target_tag_id: str,
        *,
        file_ids: list[str] | None = None,
    ) -> None:
        """Remap song-to-tag edges from one tag to another.

        Args:
            source_tag_id: Tag document ID whose references should be replaced.
            target_tag_id: Tag document ID that should receive the moved
                references.
            file_ids: Optional file document IDs to limit which song-to-tag edges
                are remapped.
        """
        if source_tag_id == target_tag_id:
            return
        all_candidate_edges = self._get_song_tag_edges_for_tags([source_tag_id, target_tag_id])
        allowed_file_ids = (
            {_as_document_id("library_files", file_id) for file_id in file_ids} if file_ids is not None else None
        )
        source_edges = [
            edge
            for edge in all_candidate_edges
            if edge.get("_to") == source_tag_id and (allowed_file_ids is None or edge.get("_from") in allowed_file_ids)
        ]
        if not source_edges:
            return

        target_existing = {
            str(edge_from)
            for edge in all_candidate_edges
            if edge.get("_to") == target_tag_id and (edge_from := edge.get("_from")) is not None
        }
        edges_to_insert = [
            {"_from": str(edge["_from"]), "_to": target_tag_id}
            for edge in source_edges
            if str(edge["_from"]) not in target_existing
        ]
        if edges_to_insert:
            self._insert_song_tag_edges(edges_to_insert)

        for edge in source_edges:
            edge_id = edge.get("_id")
            if edge_id is not None:
                self._delete_song_tag_edge_by_id(str(edge_id))

        if self._count_song_tag_edges(source_tag_id) == 0:
            self._cleanup_orphaned_tags()

    def remove_file_tags(self, file_id: str, tag_keys: list[str] | None = None) -> None:
        """Remove some or all tag edges for a file and clean up orphaned tags.

        Args:
            file_id: File document ID whose tag associations should be removed.
            tag_keys: Optional tag names to remove. When omitted, all tag edges
                for the file are deleted.
        """
        if tag_keys is None:
            self._delete_song_tag_edges_for_file(file_id)
            self._cleanup_orphaned_tags()
            return

        wanted_tag_keys = set(tag_keys)
        rows = self.get_tags_for_files_batch([file_id], include_edge=True)
        for row in rows:
            tag_doc = row.get("v")
            edge_doc = row.get("e")
            if not isinstance(tag_doc, dict) or not isinstance(edge_doc, dict):
                continue
            tag_name = tag_doc.get("name")
            edge_id = edge_doc.get("_id")
            if tag_name not in wanted_tag_keys or not isinstance(edge_id, str):
                continue
            self._delete_song_tag_edge_by_id(edge_id)
        self._cleanup_orphaned_tags()

    def _cleanup_orphaned_tags(self) -> int:
        orphaned_tag_ids = self.get_orphaned_tag_ids()
        if not orphaned_tag_ids:
            return 0
        return self.delete_tags_by_ids(orphaned_tag_ids)

    def _add_tag(self, file_id: str, payload: dict[str, Any]) -> str:
        tag_id = primitives.insert_document(self._db, self.COLLECTION, payload)
        self._upsert_tag_edge(file_id, tag_id)
        return tag_id

    def _find_or_create_tag(self, tag_key: str, value: Any) -> str:
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

    def _upsert_tag(self, file_id: str, tag_key: str, payload: dict[str, Any]) -> None:
        self.delete_tag(file_id, tag_key)
        merged_payload = dict(payload)
        merged_payload.setdefault("name", tag_key)
        self._add_tag(file_id, merged_payload)

    def get_tags_for_file(self, file_id: str) -> list[Document]:
        return cast(
            "list[Document]",
            primitives.execute(
                self._db,
                """
                FOR edge IN @@edge_collection
                    FILTER edge._from == @file_id
                    LET tag = DOCUMENT(edge._to)
                    FILTER tag != null
                    RETURN tag
                """,
                bind_vars={
                    "@edge_collection": self.EDGE_COLLECTION,
                    "file_id": _as_document_id("library_files", file_id),
                },
            ),
        )

    def _count_song_tag_edges(self, tag_id: str) -> int:
        return primitives.count_edges(
            self._db,
            self.EDGE_COLLECTION,
            "_to",
            _as_document_id(self.COLLECTION, tag_id),
        )

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
        """Return IDs of tag documents that have no song_has_tags edges."""
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
                FILTER song_edges == 0
                RETURN tag._id
            """,
            {
                "@tag_collection": self.COLLECTION,
                "@song_edge_collection": self.EDGE_COLLECTION,
            },
        )
        return [str(r) for r in results]

    def get_tags_for_files_batch(
        self,
        file_ids: list[str],
        *,
        name_starts_with: str | None = None,
        include_edge: bool = False,
    ) -> list[Document]:
        if not file_ids:
            return []
        normalized_file_ids = [_as_document_id("library_files", f) for f in file_ids]
        return_clause = "RETURN { start_id: start_file._id, v: tag }"
        if include_edge:
            return_clause = "RETURN { start_id: start_file._id, v: tag, e: edge }"
        filter_clause = ""
        if name_starts_with:
            filter_clause = "FILTER LIKE(tag.name, @name_starts_with || '%', true)"
        query = f"""
            FOR start_file IN library_files
                FILTER start_file._id IN @file_ids
                FOR edge IN @@edge_collection
                    FILTER edge._from == start_file._id
                    LET tag = DOCUMENT(edge._to)
                    FILTER tag != null
                    {filter_clause}
                    {return_clause}
        """
        bind_vars: dict[str, Any] = {
            "@edge_collection": self.EDGE_COLLECTION,
            "file_ids": normalized_file_ids,
        }
        if name_starts_with:
            bind_vars["name_starts_with"] = name_starts_with
        return cast("list[Document]", primitives.execute(self._db, query, bind_vars))

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
            "@tag_collection": self.COLLECTION,
            "@edge_collection": self.EDGE_COLLECTION,
            "limit": limit,
            "offset": offset,
        }
        filters: list[str] = []
        if name is not None:
            filters.append("FILTER tag.name == @name")
            bind_vars["name"] = name
        if search is not None:
            filters.append("FILTER LIKE(tag.name, @search, true)")
            bind_vars["search"] = search
        filter_clause = "\n            ".join(filters)
        query = f"""
            FOR tag IN @@tag_collection
                {filter_clause}
                LET song_count = LENGTH(
                    FOR edge IN @@edge_collection
                        FILTER edge._to == tag._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER song_count > 0
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

    def get_genre_tags_for_files(self, file_ids: list[str]) -> list[Document]:
        if not file_ids:
            return []
        normalized_file_ids = [_as_document_id("library_files", f) for f in file_ids]
        return cast(
            "list[Document]",
            primitives.execute(
                self._db,
                """
                FOR file_id IN @file_ids
                    FOR edge IN @@edge_collection
                        FILTER edge._from == file_id
                        LET tag = DOCUMENT(edge._to)
                        FILTER tag != null AND tag.name == "genre"
                        RETURN tag
                """,
                {
                    "@edge_collection": self.EDGE_COLLECTION,
                    "file_ids": normalized_file_ids,
                },
            ),
        )

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
        primitives.upsert_edge(
            self._db,
            self.EDGE_COLLECTION,
            _as_document_id("library_files", file_id),
            _as_document_id(self.COLLECTION, tag_id),
        )

    def _delete_song_tag_edges_for_file(self, file_id: str) -> None:
        primitives.delete_edges(
            self._db,
            self.EDGE_COLLECTION,
            from_id=_as_document_id("library_files", file_id),
        )

    def _get_song_tag_edges_for_tags(self, tag_ids: list[str], *, limit: int | None = None) -> list[Document]:
        normalized_limit = primitives.normalize_limit(limit) if limit is not None else _NO_LIMIT_COUNT
        return cast(
            "list[Document]",
            primitives.execute(
                self._db,
                """
                FOR edge IN @@edge_collection
                    FILTER edge._to IN @tag_ids
                    LIMIT @limit
                    RETURN edge
                """,
                {
                    "@edge_collection": self.EDGE_COLLECTION,
                    "tag_ids": [_as_document_id(self.COLLECTION, t) if "/" not in t else t for t in tag_ids],
                    "limit": normalized_limit,
                },
            ),
        )

    def _insert_song_tag_edges(self, edges: list[dict[str, str]]) -> None:
        primitives.insert_edges_batch(self._db, self.EDGE_COLLECTION, edges)

    def _delete_song_tag_edge_by_id(self, edge_id: str) -> None:
        primitives.delete_edge_by_key(
            self._db,
            self.EDGE_COLLECTION,
            _extract_key(edge_id),
        )

    def delete_tag(self, file_id: str, tag_key: str) -> None:
        self.remove_file_tags(file_id, [tag_key])

    def _truncate_collection(self, collection_name: str) -> None:
        self._db.aql.execute(
            """
            FOR doc IN @@collection
                REMOVE doc IN @@collection OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"@collection": collection_name},
        )
