from __future__ import annotations

from typing import Any

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.schema import CollectionNames

Document = dict[str, Any]


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


class MlStreamsAqlOperations:
    """Thin Tier 2 bindings for ML output streams and related edges."""

    COLLECTION = CollectionNames.ML_OUTPUT_STREAMS.value
    FILE_EDGE_COLLECTION = CollectionNames.FILE_HAS_OUTPUT_STREAM.value
    OUTPUT_EDGE_COLLECTION = CollectionNames.OUTPUT_HAS_STREAM.value
    FILE_COLLECTION = CollectionNames.LIBRARY_FILES.value

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def get_output_streams_for_file(self, file_id: str) -> list[Document]:
        return primitives.execute(
            self._db,
            """
            FOR edge IN @@file_edge_collection
                FILTER edge._from == @file_id
                LET stream = DOCUMENT(edge._to)
                FILTER stream != null
                LET output_doc = FIRST(
                    FOR output_edge IN @@output_edge_collection
                        FILTER output_edge._to == stream._id
                        LET output = DOCUMENT(output_edge._from)
                        FILTER output != null
                        LIMIT 1
                        RETURN output
                )
                SORT stream._key
                RETURN MERGE(
                    stream,
                    {
                        output_id: output_doc == null ? null : output_doc._id,
                        output_index: output_doc == null ? null : output_doc.output_index,
                    }
                )
            """,
            {
                "@file_edge_collection": self.FILE_EDGE_COLLECTION,
                "@output_edge_collection": self.OUTPUT_EDGE_COLLECTION,
                "file_id": _as_document_id(self.FILE_COLLECTION, file_id),
            },
        )

    def upsert_output_streams_batch(self, file_id: str, stream_payloads: list[dict[str, Any]]) -> None:
        """Upsert streams and related edges for ``file_id`` in one query."""
        if not stream_payloads:
            return
        normalized_file_id = _as_document_id(self.FILE_COLLECTION, file_id)

        # Ensure every payload has a _key so the batch UPSERT can match.
        docs = []
        for payload in stream_payloads:
            doc = dict(payload)
            if not isinstance(doc.get("_key"), str) or not doc["_key"]:
                import uuid

                doc["_key"] = uuid.uuid4().hex
            docs.append(doc)

        primitives.execute(
            self._db,
            """
            FOR doc IN @docs
                UPSERT { _key: doc._key }
                    INSERT doc
                    UPDATE doc
                    IN @@stream_collection
                LET stream_id = NEW._id
                UPSERT { _from: @file_id, _to: stream_id }
                    INSERT { _from: @file_id, _to: stream_id }
                    UPDATE {}
                    IN @@file_edge_collection
                FILTER doc.output_id != null
                UPSERT { _from: doc.output_id, _to: stream_id }
                    INSERT { _from: doc.output_id, _to: stream_id }
                    UPDATE {}
                    IN @@output_edge_collection
            """,
            {
                "@stream_collection": self.COLLECTION,
                "@file_edge_collection": self.FILE_EDGE_COLLECTION,
                "@output_edge_collection": self.OUTPUT_EDGE_COLLECTION,
                "file_id": normalized_file_id,
                "docs": docs,
            },
        )

    def delete_output_streams_for_file(self, file_id: str) -> None:
        self._db.aql.execute(
            """
            LET file_edge_data = (
                FOR e IN @@file_edge_collection
                    FILTER e._from == @file_id
                    RETURN {id: e._to, edge: e}
            )
            LET stream_ids = file_edge_data[* RETURN CURRENT.id]
            LET file_edges = file_edge_data[* RETURN CURRENT.edge]
            LET output_edges = (
                FOR e IN @@output_edge_collection
                    FILTER e._to IN stream_ids
                    RETURN e
            )
            FOR oe IN output_edges
                REMOVE oe IN @@output_edge_collection OPTIONS { ignoreErrors: true }
            FOR stream_id IN stream_ids
                REMOVE stream_id IN @@collection
                OPTIONS { ignoreErrors: true }
            FOR fe IN file_edges
                REMOVE fe IN @@file_edge_collection OPTIONS { ignoreErrors: true }
            """,
            bind_vars={
                "@collection": self.COLLECTION,
                "@file_edge_collection": self.FILE_EDGE_COLLECTION,
                "@output_edge_collection": self.OUTPUT_EDGE_COLLECTION,
                "file_id": _as_document_id(self.FILE_COLLECTION, file_id),
            },
        )
