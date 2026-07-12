from __future__ import annotations

from typing import Any

from nomarr.helpers.constants.file_states import ALL_STATE_VERTICES, STATE_NOT_PROCESSED, STATE_PROCESSED
from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.schema import CollectionNames

_NEGATIVE_FILE_STATES = tuple(state for state in ALL_STATE_VERTICES if state.startswith("file_states/not_"))


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


class FileStatesAqlOperations:
    """Thin Tier 2 bindings for file-state graph operations."""

    FILE_COLLECTION = CollectionNames.LIBRARY_FILES.value
    STATE_COLLECTION = CollectionNames.FILE_STATES.value
    EDGE_COLLECTION = CollectionNames.FILE_HAS_STATE.value

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
                "file_id": _as_document_id(self.FILE_COLLECTION, file_id),
            },
        )
        results = list(cursor)
        return str(results[0]) if results else None

    def get_file_states_for_files(self, file_ids: list[str]) -> dict[str, set[str]]:
        """Return a mapping of file_id → current state values for the given files.

        Single edge-traversal query — no full scan, no document fetch.
        """
        if not file_ids:
            return {}
        normalized_ids = [_as_document_id(self.FILE_COLLECTION, fid) for fid in file_ids]
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@edge_collection
                FILTER edge._from IN @file_ids
                RETURN {file_id: edge._from, state: PARSE_IDENTIFIER(edge._to).key}
            """,
            bind_vars={
                "@edge_collection": self.EDGE_COLLECTION,
                "file_ids": normalized_ids,
            },
        )
        result: dict[str, set[str]] = {}
        for row in cursor:
            result.setdefault(row["file_id"], set()).add(row["state"])
        return result

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
        normalized_ids = [_as_document_id(self.FILE_COLLECTION, file_id) for file_id in file_ids]
        edge_collection = self.EDGE_COLLECTION
        from_state_id = _as_document_id(self.STATE_COLLECTION, from_state)
        to_state_id = _as_document_id(self.STATE_COLLECTION, to_state)
        self._db.aql.execute(
            """
            FOR edge IN @@edge_collection
                FILTER edge._from IN @file_ids AND edge._to == @from_state_id
                REMOVE edge IN @@edge_collection OPTIONS { ignoreErrors: true }
            """,
            bind_vars={
                "@edge_collection": edge_collection,
                "file_ids": normalized_ids,
                "from_state_id": from_state_id,
            },
        )
        self._db.aql.execute(
            """
            FOR edge IN @@edge_collection
                FILTER edge._from IN @file_ids AND edge._to == @to_state_id
                REMOVE edge IN @@edge_collection OPTIONS { ignoreErrors: true }
            """,
            bind_vars={
                "@edge_collection": edge_collection,
                "file_ids": normalized_ids,
                "to_state_id": to_state_id,
            },
        )
        self._db.aql.execute(
            """
            FOR file_id IN @file_ids
                INSERT { _from: file_id, _to: @to_state_id }
                IN @@edge_collection
            """,
            bind_vars={
                "@edge_collection": edge_collection,
                "file_ids": normalized_ids,
                "to_state_id": to_state_id,
            },
        )

    def bootstrap_file_states(self, file_ids: list[str]) -> None:
        """Create the initial negative state edges for each new file.

        Args:
            file_ids: File document IDs to initialize. Duplicate IDs are ignored.
        """
        unique_file_ids = list(dict.fromkeys(file_ids))
        for file_id in unique_file_ids:
            for state in _NEGATIVE_FILE_STATES:
                self.add_file_state_edge(file_id, state)

    def mark_files_processed(self, file_ids: list[str]) -> None:
        """Transition files from the not-processed state to the processed state.

        Args:
            file_ids: File document IDs to mark as processed. Duplicate IDs are
                ignored.
        """
        unique_file_ids = list(dict.fromkeys(file_ids))
        if not unique_file_ids:
            return
        self.transition_file_states(unique_file_ids, STATE_NOT_PROCESSED, STATE_PROCESSED)

    def add_file_state_edge(self, file_id: str, state: str) -> None:
        primitives.upsert_edge(
            self._db,
            self.EDGE_COLLECTION,
            _as_document_id(self.FILE_COLLECTION, file_id),
            _as_document_id(self.STATE_COLLECTION, state),
        )

    def delete_file_state_edges(self, file_ids: list[str]) -> None:
        normalized_ids = [_as_document_id(self.FILE_COLLECTION, file_id) for file_id in file_ids]
        primitives.delete_edges_by_from_list(self._db, self.EDGE_COLLECTION, normalized_ids)

    def count_files_in_state(self, state: str) -> int:
        return primitives.count_edges(
            self._db,
            self.EDGE_COLLECTION,
            "_to",
            _as_document_id(self.STATE_COLLECTION, state),
        )
