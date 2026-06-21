"""Tier 2 AQL bindings for canonical int8 temporal embedding streams.

This module provides the ``MlEmbeddingStreamsAqlOperations`` class, which
handles CRUD operations for the ``ml_embedding_streams`` document collection
and the ``file_has_embedding_stream`` edge collection.
"""

from __future__ import annotations

import hashlib
from typing import Any, cast

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.schema import CollectionNames

Document = dict[str, Any]


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


def _compute_embedding_stream_key(file_id: str, backbone: str) -> str:
    """Compute the deterministic ``_key`` for an embedding stream document.

    The key is derived from the file ID and backbone name so that any caller
    with access to both can look up the stream without a separate index query.
    """
    return hashlib.sha256(f"{file_id}|{backbone}".encode()).hexdigest()[:16]


class MlEmbeddingStreamsAqlOperations:
    """Thin Tier 2 bindings for ML embedding streams and related edges.

    Each embedding stream document stores an int8-quantized backbone patch
    stream for one ``(file, backbone)`` pair. The deterministic ``_key`` is
    computed by the component layer, not by this class, except for the
    ``get`` method which derives it from ``file_id`` and ``backbone``.
    """

    COLLECTION = CollectionNames.ML_EMBEDDING_STREAMS.value
    FILE_EDGE_COLLECTION = CollectionNames.FILE_HAS_EMBEDDING_STREAM.value
    FILE_COLLECTION = CollectionNames.LIBRARY_FILES.value

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def get_embedding_stream_for_file(self, file_id: str, backbone: str) -> Document | None:
        """Look up an embedding stream document by deterministic ``_key``.

        The ``_key`` is computed as ``sha256(file_id | backbone)[:16]`` so
        this is a direct document lookup — no AQL ``FILTER`` needed.
        """
        stream_key = _compute_embedding_stream_key(file_id, backbone)
        results = primitives.get_many_by_keys(self._db, self.COLLECTION, [stream_key])
        return results[0] if results else None

    def upsert_embedding_stream(self, file_id: str, payload: dict[str, Any]) -> str:
        """Upsert an embedding stream document and ensure the file edge.

        The ``payload`` dict must contain the deterministic ``_key`` (set by
        the caller/component layer). After upserting the document, the
        ``file_has_embedding_stream`` edge is created if it does not already
        exist.
        """
        normalized_file_id = _as_document_id(self.FILE_COLLECTION, file_id)
        stream_key = payload.get("_key")
        if isinstance(stream_key, str) and stream_key:
            cursor = self._db.aql.execute(
                """
                UPSERT { _key: @stream_key }
                    INSERT MERGE(@payload, { _key: @stream_key })
                    UPDATE @payload
                    IN @@collection
                    RETURN NEW._id
                """,
                bind_vars={
                    "@collection": self.COLLECTION,
                    "stream_key": stream_key,
                    "payload": payload,
                },
            )
            results = list(cursor)
            stream_id = cast("str", results[0])
        else:
            stream_id = primitives.insert_document(self._db, self.COLLECTION, payload)
        self._upsert_edge(self.FILE_EDGE_COLLECTION, normalized_file_id, stream_id)
        return stream_id

    def delete_embedding_streams_for_file(self, file_id: str) -> None:
        """Delete all embedding streams and their edges for a file.

        Finds all ``file_has_embedding_stream`` edges pointing from the given
        file, removes the stream documents they reference, and then removes the
        edges themselves.
        """
        normalized_file_id = _as_document_id(self.FILE_COLLECTION, file_id)
        self._db.aql.execute(
            """
            LET file_edge_data = (
                FOR e IN @@file_edge_collection
                    FILTER e._from == @file_id
                    RETURN {id: e._to, edge: e}
            )
            LET stream_ids = file_edge_data[* RETURN CURRENT.id]
            LET file_edges = file_edge_data[* RETURN CURRENT.edge]
            FOR stream_id IN stream_ids
                REMOVE stream_id IN @@collection
                OPTIONS { ignoreErrors: true }
            FOR fe IN file_edges
                REMOVE fe IN @@file_edge_collection
                OPTIONS { ignoreErrors: true }
            """,
            bind_vars={
                "@collection": self.COLLECTION,
                "@file_edge_collection": self.FILE_EDGE_COLLECTION,
                "file_id": normalized_file_id,
            },
        )

    def list_embedding_streams_by_backbone(
        self,
        backbone: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        """List embedding streams for a backbone with pagination.

        Results are sorted by ``_key`` for stable pagination.
        """
        return primitives.execute(
            self._db,
            """
            FOR doc IN @@collection
                FILTER doc.backbone == @backbone
                SORT doc._key
                LIMIT @offset, @limit
                RETURN doc
            """,
            {
                "@collection": self.COLLECTION,
                "backbone": backbone,
                "offset": offset,
                "limit": limit,
            },
        )

    def count_embedding_streams(self, backbone: str) -> int:
        """Count the number of embedding streams for a backbone."""
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER doc.backbone == @backbone
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@collection": self.COLLECTION, "backbone": backbone},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def _upsert_edge(self, collection: str, from_id: str, to_id: str) -> None:
        primitives.upsert_edge(self._db, collection, from_id, to_id)
