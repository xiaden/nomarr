from __future__ import annotations

from typing import Any, cast

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase

Document = dict[str, Any]


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


class MlStreamsAqlOperations:
    """Thin Tier 2 bindings for ML output streams and related edges."""

    COLLECTION = "ml_output_streams"
    FILE_EDGE_COLLECTION = "file_has_output_stream"
    OUTPUT_EDGE_COLLECTION = "output_has_stream"

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
                "file_id": _as_document_id("library_files", file_id),
            },
        )

    def upsert_output_streams_batch(self, file_id: str, stream_payloads: list[dict[str, Any]]) -> None:
        normalized_file_id = _as_document_id("library_files", file_id)
        for payload in stream_payloads:
            stream_id = self._upsert_stream_document(payload)
            self._upsert_edge(self.FILE_EDGE_COLLECTION, normalized_file_id, stream_id)
            output_id = payload.get("output_id")
            if isinstance(output_id, str) and output_id:
                self._upsert_edge(self.OUTPUT_EDGE_COLLECTION, output_id, stream_id)

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
                "file_id": _as_document_id("library_files", file_id),
            },
        )

    def _upsert_stream_document(self, payload: dict[str, Any]) -> str:
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
                bind_vars={"@collection": self.COLLECTION, "stream_key": stream_key, "payload": payload},
            )
            results = list(cursor)
            return cast("str", results[0])
        return primitives.insert_document(self._db, self.COLLECTION, payload)

    def _upsert_edge(self, collection: str, from_id: str, to_id: str) -> None:
        primitives.upsert_edge(self._db, collection, from_id, to_id)
