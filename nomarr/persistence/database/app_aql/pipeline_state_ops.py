from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.persistence.aql import primitives

from ._helpers import Document, _as_document_id, _extract_key

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import SafeDatabase


class PipelineStateOpsMixin:
    """Mixin for pipeline state, scan, and related edge operations.

    Requires the host class to provide ``self._db`` (a ``SafeDatabase``),
    collection name constants, field-set constants, and
    ``self._truncate_collection()``.
    """

    _db: SafeDatabase
    PIPELINE_STATE_COLLECTION: str
    PIPELINE_STATE_EDGE_COLLECTION: str
    FILE_STATE_EDGE_COLLECTION: str
    SCAN_COLLECTION: str
    LIBRARY_SCAN_EDGE_COLLECTION: str
    PIPELINE_STATE_FIELDS: frozenset[str]
    SCAN_FIELDS: frozenset[str]

    def _truncate_collection(self, collection_name: str) -> None: ...

    def upsert_pipeline_state(self, library_id: str, state: str) -> None:
        library_key = _extract_key(library_id)
        payload = {"library_key": library_key, "pipeline_state": state}
        primitives.upsert_by_field(self._db, self.PIPELINE_STATE_COLLECTION, "library_key", library_key, payload)

    def get_pipeline_state_doc(self, library_id: str) -> Document | None:
        results = primitives.get_many_by_field(
            self._db,
            self.PIPELINE_STATE_COLLECTION,
            "library_key",
            _extract_key(library_id),
            limit=1,
            allowed_fields=self.PIPELINE_STATE_FIELDS,
        )
        return results[0] if results else None

    def update_pipeline_state(self, library_id: str, state: str) -> None:
        pipeline_state_doc = self.get_pipeline_state_doc(library_id)
        if pipeline_state_doc is None:
            return
        pipeline_key = pipeline_state_doc.get("_key")
        if isinstance(pipeline_key, str):
            primitives.update_document_by_key(
                self._db,
                self.PIPELINE_STATE_COLLECTION,
                pipeline_key,
                {"pipeline_state": state},
            )

    def delete_pipeline_state(self, library_id: str) -> int:
        return primitives.delete_many_by_field(
            self._db,
            self.PIPELINE_STATE_COLLECTION,
            "library_key",
            _extract_key(library_id),
            allowed_fields=self.PIPELINE_STATE_FIELDS,
        )

    def count_pipeline_states(self) -> int:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@collection": self.PIPELINE_STATE_COLLECTION},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def list_libraries_in_pipeline_state(self, state: str) -> list[Document]:
        return primitives.get_filtered_docs(
            self._db,
            self.PIPELINE_STATE_COLLECTION,
            filters={"pipeline_state": state},
            sort_field="library_key",
            limit=None,
            allowed_fields=self.PIPELINE_STATE_FIELDS,
        )

    def delete_pipeline_state_edges_for_library(self, library_id: str) -> None:
        primitives.delete_edges(
            self._db,
            self.PIPELINE_STATE_EDGE_COLLECTION,
            from_id=_as_document_id("libraries", library_id),
        )

    def list_file_docs_in_state(self, state: str, *, limit: int | None = None) -> list[Document]:
        bind_vars: dict[str, Any] = {
            "@edge_collection": self.FILE_STATE_EDGE_COLLECTION,
            "state_id": _as_document_id("file_states", state),
        }
        query_lines = [
            "FOR edge IN @@edge_collection",
            "    FILTER edge._to == @state_id",
            "    LET file = DOCUMENT(edge._from)",
            "    FILTER file != null",
            "    SORT file._key",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN file")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def get_state_edges_for_files(self, file_ids: list[str]) -> list[Document]:
        normalized_ids = [_as_document_id("library_files", file_id) for file_id in file_ids]
        if not normalized_ids:
            return []
        return primitives.execute(
            self._db,
            """
            FOR edge IN @@collection
                FILTER edge._from IN @file_ids
                SORT edge._from, edge._to, edge._key
                RETURN edge
            """,
            {"@collection": self.FILE_STATE_EDGE_COLLECTION, "file_ids": normalized_ids},
        )

    def delete_scan_records_for_library(self, library_key: str) -> int:
        return primitives.delete_many_by_field(
            self._db,
            self.SCAN_COLLECTION,
            "library_key",
            library_key,
            allowed_fields=self.SCAN_FIELDS,
        )

    def upsert_library_scan_edge(self, library_id: str, scan_id: str) -> None:
        primitives.upsert_edge(
            self._db,
            self.LIBRARY_SCAN_EDGE_COLLECTION,
            _as_document_id("libraries", library_id),
            _as_document_id(self.SCAN_COLLECTION, scan_id),
        )

    def delete_library_scan_edge(self, library_id: str) -> None:
        primitives.delete_edges(
            self._db,
            self.LIBRARY_SCAN_EDGE_COLLECTION,
            from_id=_as_document_id("libraries", library_id),
        )

    def truncate_file_state_edges(self) -> None:
        self._truncate_collection(self.FILE_STATE_EDGE_COLLECTION)

    def truncate_scan_records(self) -> None:
        self._truncate_collection(self.SCAN_COLLECTION)

    def truncate_library_scan_edges(self) -> None:
        self._truncate_collection(self.LIBRARY_SCAN_EDGE_COLLECTION)

    def truncate_pipeline_states(self) -> None:
        self._truncate_collection(self.PIPELINE_STATE_COLLECTION)

    def truncate_pipeline_state_edges(self) -> None:
        self._truncate_collection(self.PIPELINE_STATE_EDGE_COLLECTION)
