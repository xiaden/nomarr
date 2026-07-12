from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.aql import primitives
from nomarr.persistence.schema import CollectionNames

from ._helpers import _NO_LIMIT_COUNT, Document, _as_document_id, _extract_key

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import SafeDatabase


class TagEdgeOpsMixin:
    """Mixin for tag edge CRUD, orphan cleanup, and batch-query operations.

    Requires the host class to provide ``self._db`` (a ``SafeDatabase``),
    ``self.COLLECTION``, ``self.EDGE_COLLECTION``,
    ``self.FILE_STATE_EDGE_COLLECTION``, and ``self._truncate_collection()``.
    """

    _db: SafeDatabase
    COLLECTION: str
    EDGE_COLLECTION: str
    FILE_STATE_EDGE_COLLECTION: str
    FILE_COLLECTION: str = CollectionNames.LIBRARY_FILES.value
    LIBRARY_COLLECTION: str = CollectionNames.LIBRARIES.value
    FILE_STATES_COLLECTION: str = CollectionNames.FILE_STATES.value

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

        # Validate all tags up front and collect unique (name, value) pairs.
        tag_pairs: list[tuple[str, Any]] = []
        seen_pairs: set[tuple[str, Any]] = set()
        for payload in tags:
            tag_name = payload.get("name", payload.get("key"))
            if not isinstance(tag_name, str) or not tag_name:
                msg = "Tag payload must include a non-empty 'name' or 'key'"
                raise ValueError(msg)
            if "value" not in payload:
                msg = f"Tag payload for {tag_name!r} must include 'value'"
                raise ValueError(msg)
            pair = (tag_name, payload["value"])
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                tag_pairs.append(pair)

        # Batch find-or-create all unique tag documents in one query.
        pair_to_id = self._find_or_create_tags_batch(tag_pairs)

        # Batch insert edges (fresh after delete, so INSERT is safe).
        normalized_file_id = _as_document_id(self.FILE_COLLECTION, file_id)
        edge_docs = []
        for pair in tag_pairs:
            tag_id = pair_to_id[pair]
            edge_docs.append({"_from": normalized_file_id, "_to": tag_id})

        primitives.insert_edges_batch(self._db, self.EDGE_COLLECTION, edge_docs)
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
            {_as_document_id(self.FILE_COLLECTION, file_id) for file_id in file_ids} if file_ids is not None else None
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
        if isinstance(value, list | tuple | dict | set):
            msg = f"Tag value must be a scalar (str|int|float|bool), got {type(value).__name__}: {value!r}"
            raise ValueError(msg)
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

    def _find_or_create_tags_batch(
        self,
        pairs: list[tuple[str, Any]],
    ) -> dict[tuple[str, Any], str]:
        """Batch find-or-create tag documents for a set of (name, value) pairs.

        Returns a mapping from (name, value) to the tag document ``_id``.
        Short-circuits to an empty dict when ``pairs`` is empty.
        """
        if not pairs:
            return {}

        docs = [{"name": name, "value": value} for name, value in pairs]
        rows = primitives.execute(
            self._db,
            """
            FOR doc IN @docs
                UPSERT { name: doc.name, value: doc.value }
                    INSERT doc
                    UPDATE {}
                    IN @@collection
                RETURN { name: doc.name, value: doc.value, _id: NEW._id }
            """,
            {"@collection": self.COLLECTION, "docs": docs},
        )
        result: dict[tuple[str, Any], str] = {}
        for row in rows:
            name = row.get("name")
            value = row.get("value")
            tag_id = row.get("_id")
            if isinstance(name, str) and value is not None and isinstance(tag_id, str):
                result[(name, value)] = tag_id
        return result

    def _upsert_tag(self, file_id: str, tag_key: str, payload: dict[str, Any]) -> None:
        self.delete_tag(file_id, tag_key)
        merged_payload = dict(payload)
        merged_payload.setdefault("name", tag_key)
        self._add_tag(file_id, merged_payload)

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
                "file_id": _as_document_id(self.FILE_COLLECTION, file_id),
                "state_id": _as_document_id(self.FILE_STATES_COLLECTION, state_tag_id),
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
        normalized_file_ids = [_as_document_id(self.FILE_COLLECTION, f) for f in file_ids]
        return_clause = "RETURN { start_id: start_file._id, v: tag }"
        if include_edge:
            return_clause = "RETURN { start_id: start_file._id, v: tag, e: edge }"
        filter_clause = ""
        if name_starts_with:
            filter_clause = "FILTER LIKE(tag.name, @name_starts_with || '%', true)"
        query = f"""
            FOR start_file IN @@file_collection
                FILTER start_file._id IN @file_ids
                FOR edge IN @@edge_collection
                    FILTER edge._from == start_file._id
                    LET tag = DOCUMENT(edge._to)
                    FILTER tag != null
                    {filter_clause}
                    {return_clause}
        """
        bind_vars: dict[str, Any] = {
            "@file_collection": self.FILE_COLLECTION,
            "@edge_collection": self.EDGE_COLLECTION,
            "file_ids": normalized_file_ids,
        }
        if name_starts_with:
            bind_vars["name_starts_with"] = name_starts_with
        return cast("list[Document]", primitives.execute(self._db, query, bind_vars))

    def get_genre_tags_for_files(self, file_ids: list[str]) -> list[Document]:
        if not file_ids:
            return []
        normalized_file_ids = [_as_document_id(self.FILE_COLLECTION, f) for f in file_ids]
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

    def _upsert_tag_edge(self, file_id: str, tag_id: str) -> None:
        primitives.upsert_edge(
            self._db,
            self.EDGE_COLLECTION,
            _as_document_id(self.FILE_COLLECTION, file_id),
            _as_document_id(self.COLLECTION, tag_id),
        )

    def _delete_song_tag_edges_for_file(self, file_id: str) -> None:
        primitives.delete_edges(
            self._db,
            self.EDGE_COLLECTION,
            from_id=_as_document_id(self.FILE_COLLECTION, file_id),
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
