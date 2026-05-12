from __future__ import annotations

from typing import Any

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


class FileStatesAqlOperations:
    """Thin Tier 2 bindings for file-state graph operations."""

    STATE_COLLECTION = "file_states"
    EDGE_COLLECTION = "file_has_state"

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def get_file_state(self, file_id: str) -> str | None:
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@edge_collection
                FILTER edge._from == @file_id
                SORT edge._to
                LIMIT 1
                RETURN PARSE_IDENTIFIER(edge._to).key
            """,
            bind_vars={
                "@edge_collection": self.EDGE_COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
            },
        )
        results = list(cursor)
        return str(results[0]) if results else None

    def list_files_in_state(self, state: str, *, limit: int | None = None) -> list[str]:
        bind_vars: dict[str, Any] = {
            "@edge_collection": self.EDGE_COLLECTION,
            "state_id": _as_document_id(self.STATE_COLLECTION, state),
        }
        query_lines = [
            "FOR edge IN @@edge_collection",
            "    FILTER edge._to == @state_id",
            "    SORT edge._from",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN edge._from")
        cursor = self._db.aql.execute("\n".join(query_lines), bind_vars=bind_vars)
        return list(cursor)

    def transition_file_states(self, file_ids: list[str], from_state: str, to_state: str) -> None:
        if not file_ids:
            return
        normalized_ids = [_as_document_id("library_files", file_id) for file_id in file_ids]
        bind_vars = {
            "@edge_collection": self.EDGE_COLLECTION,
            "file_ids": normalized_ids,
            "from_state_id": _as_document_id(self.STATE_COLLECTION, from_state),
            "to_state_id": _as_document_id(self.STATE_COLLECTION, to_state),
        }
        self._db.aql.execute(
            """
            FOR edge IN @@edge_collection
                FILTER edge._from IN @file_ids AND edge._to == @from_state_id
                REMOVE edge IN @@edge_collection
            """,
            bind_vars=bind_vars,
        )
        self._db.aql.execute(
            """
            FOR file_id IN @file_ids
                UPSERT { _from: file_id, _to: @to_state_id }
                    INSERT { _from: file_id, _to: @to_state_id }
                    UPDATE {}
                    IN @@edge_collection
            """,
            bind_vars=bind_vars,
        )

    def add_file_state_edge(self, file_id: str, state: str) -> None:
        self._db.aql.execute(
            """
            UPSERT { _from: @file_id, _to: @state_id }
                INSERT { _from: @file_id, _to: @state_id }
                UPDATE {}
                IN @@edge_collection
            """,
            bind_vars={
                "@edge_collection": self.EDGE_COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
                "state_id": _as_document_id(self.STATE_COLLECTION, state),
            },
        )

    def delete_file_state_edges(self, file_ids: list[str]) -> None:
        if not file_ids:
            return
        normalized_ids = [_as_document_id("library_files", file_id) for file_id in file_ids]
        self._db.aql.execute(
            """
            FOR edge IN @@edge_collection
                FILTER edge._from IN @file_ids
                REMOVE edge IN @@edge_collection
            """,
            bind_vars={"@edge_collection": self.EDGE_COLLECTION, "file_ids": normalized_ids},
        )

    def count_files_in_state(self, state: str) -> int:
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@edge_collection
                FILTER edge._to == @state_id
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={
                "@edge_collection": self.EDGE_COLLECTION,
                "state_id": _as_document_id(self.STATE_COLLECTION, state),
            },
        )
        results = list(cursor)
        return int(results[0]) if results else 0
