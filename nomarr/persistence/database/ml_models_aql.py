from __future__ import annotations

from typing import Any, cast

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase

Document = dict[str, Any]


def _extract_key(document_id_or_key: str) -> str:
    return document_id_or_key.split("/", 1)[1] if "/" in document_id_or_key else document_id_or_key


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


class MlModelsAqlOperations:
    """Thin Tier 2 bindings for models, outputs, and calibration state."""

    MODEL_COLLECTION = "ml_models"
    MODEL_OUTPUT_COLLECTION = "ml_model_outputs"
    MODEL_OUTPUT_EDGE_COLLECTION = "model_has_output"
    TAG_MODEL_OUTPUT_COLLECTION = "tag_model_output"
    TAG_COLLECTION = "tags"
    CALIBRATION_COLLECTION = "calibration_state"
    CALIBRATION_EDGE_COLLECTION = "model_has_calibration"
    CALIBRATION_HISTORY_COLLECTION = "calibration_history"

    MODEL_FIELDS = frozenset(
        {
            "path",
            "backbone",
            "head_type",
            "model_stem",
            "output_count",
            "fully_configured",
            "is_known",
            "source",
            "head_release_date",
            "embedder_release_date",
            "registered_at",
            "updated_at",
        },
    )

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def get_model(self, model_id: str) -> Document | None:
        results = primitives.get_many_by_keys(self._db, self.MODEL_COLLECTION, [_extract_key(model_id)])
        return results[0] if results else None

    def get_model_by_path(self, path: str) -> Document | None:
        results = primitives.get_many_by_field(
            self._db,
            self.MODEL_COLLECTION,
            "path",
            path,
            limit=1,
            allowed_fields=self.MODEL_FIELDS,
        )
        return results[0] if results else None

    def upsert_model(self, payload: dict[str, Any]) -> None:
        model_path = payload.get("path")
        model_key = payload.get("_key")
        if isinstance(model_path, str) and model_path:
            primitives.upsert_by_field(self._db, self.MODEL_COLLECTION, "path", model_path, payload)
            return
        if isinstance(model_key, str) and model_key:
            self._db.aql.execute(
                """
                UPSERT { _key: @model_key }
                    INSERT MERGE(@payload, { _key: @model_key })
                    UPDATE @payload
                    IN @@collection
                """,
                bind_vars={"@collection": self.MODEL_COLLECTION, "model_key": model_key, "payload": payload},
            )
            return
        msg = "Model payload must include either 'path' or '_key'"
        raise ValueError(msg)

    def delete_model(self, model_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.MODEL_COLLECTION, [_extract_key(model_id)])

    def list_models(self) -> list[Document]:
        return primitives.get_filtered_docs(
            self._db,
            self.MODEL_COLLECTION,
            filters={},
            sort_field="path",
            limit=None,
            allowed_fields=self.MODEL_FIELDS,
        )

    def count_models(self) -> int:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@collection": self.MODEL_COLLECTION},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def get_models_by_ids(self, model_ids: list[str]) -> list[Document]:
        return primitives.get_many_by_keys(
            self._db, self.MODEL_COLLECTION, [_extract_key(model_id) for model_id in model_ids]
        )

    def get_model_output(self, output_id: str) -> Document | None:
        results = primitives.get_many_by_keys(self._db, self.MODEL_OUTPUT_COLLECTION, [_extract_key(output_id)])
        return results[0] if results else None

    def list_model_outputs(self, model_id: str) -> list[Document]:
        return primitives.execute(
            self._db,
            """
            FOR output IN OUTBOUND @model_id @@edge_collection
                FILTER IS_SAME_COLLECTION(@output_collection, output)
                SORT output.output_index, output._key
                RETURN output
            """,
            {
                "@edge_collection": self.MODEL_OUTPUT_EDGE_COLLECTION,
                "model_id": _as_document_id(self.MODEL_COLLECTION, model_id),
                "output_collection": self.MODEL_OUTPUT_COLLECTION,
            },
        )

    def add_model_output(self, payload: dict[str, Any]) -> str:
        return primitives.insert_document(self._db, self.MODEL_OUTPUT_COLLECTION, payload)

    def update_model_output(self, output_id: str, fields: dict[str, Any]) -> None:
        primitives.update_document_by_key(self._db, self.MODEL_OUTPUT_COLLECTION, _extract_key(output_id), fields)

    def upsert_model_output_edge(self, output_key: str, model_id: str, output_id: str) -> None:
        self._db.aql.execute(
            """
            UPSERT { _key: @edge_key }
                INSERT { _key: @edge_key, _from: @model_id, _to: @output_id }
                UPDATE { _from: @model_id, _to: @output_id }
                IN @@collection
            """,
            bind_vars={
                "@collection": self.MODEL_OUTPUT_EDGE_COLLECTION,
                "edge_key": output_key,
                "model_id": _as_document_id(self.MODEL_COLLECTION, model_id),
                "output_id": _as_document_id(self.MODEL_OUTPUT_COLLECTION, output_id),
            },
        )

    def delete_model_output(self, output_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.MODEL_OUTPUT_COLLECTION, [_extract_key(output_id)])

    def delete_model_outputs_for_model(self, model_id: str) -> list[str]:
        normalized_model_id = _as_document_id(self.MODEL_COLLECTION, model_id)
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@edge_collection
                FILTER edge._from == @model_id
                SORT edge._key
                RETURN edge._to
            """,
            bind_vars={"@edge_collection": self.MODEL_OUTPUT_EDGE_COLLECTION, "model_id": normalized_model_id},
        )
        output_ids = [str(output_id) for output_id in cursor]
        if not output_ids:
            return []
        self._db.aql.execute(
            """
            FOR output_id IN @output_ids
                REMOVE output_id IN @@output_collection
                OPTIONS { ignoreErrors: true }
            FOR edge IN @@edge_collection
                FILTER edge._from == @model_id
                REMOVE edge IN @@edge_collection
            """,
            bind_vars={
                "@output_collection": self.MODEL_OUTPUT_COLLECTION,
                "@edge_collection": self.MODEL_OUTPUT_EDGE_COLLECTION,
                "output_ids": output_ids,
                "model_id": normalized_model_id,
            },
        )
        return output_ids

    def get_tag_model_output(self, key: str) -> Document | None:
        results = primitives.get_many_by_keys(self._db, self.TAG_MODEL_OUTPUT_COLLECTION, [_extract_key(key)])
        return results[0] if results else None

    def get_tag_model_output_edges_for_tags(self, tag_ids: list[str]) -> list[Document]:
        normalized_tag_ids = [_as_document_id(self.TAG_COLLECTION, tag_id) for tag_id in tag_ids]
        if not normalized_tag_ids:
            return []
        return primitives.execute(
            self._db,
            """
            FOR edge IN @@collection
                FILTER edge._from IN @tag_ids
                SORT edge._from, edge._to, edge._key
                RETURN edge
            """,
            {"@collection": self.TAG_MODEL_OUTPUT_COLLECTION, "tag_ids": normalized_tag_ids},
        )

    def upsert_tag_model_output(self, payload: dict[str, Any]) -> None:
        edge_from = payload.get("_from")
        edge_to = payload.get("_to")
        edge_key = payload.get("_key")
        if isinstance(edge_from, str) and isinstance(edge_to, str):
            self._db.aql.execute(
                """
                UPSERT { _from: @edge_from, _to: @edge_to }
                    INSERT MERGE(@payload, { _from: @edge_from, _to: @edge_to })
                    UPDATE @payload
                    IN @@collection
                """,
                bind_vars={
                    "@collection": self.TAG_MODEL_OUTPUT_COLLECTION,
                    "edge_from": edge_from,
                    "edge_to": edge_to,
                    "payload": payload,
                },
            )
            return
        if isinstance(edge_key, str) and edge_key:
            self._db.aql.execute(
                """
                UPSERT { _key: @edge_key }
                    INSERT MERGE(@payload, { _key: @edge_key })
                    UPDATE @payload
                    IN @@collection
                """,
                bind_vars={"@collection": self.TAG_MODEL_OUTPUT_COLLECTION, "edge_key": edge_key, "payload": payload},
            )
            return
        msg = "Tag model output payload must include '_key' or both '_from' and '_to'"
        raise ValueError(msg)

    def insert_tag_model_output_edges_batch(self, docs: list[dict[str, Any]]) -> None:
        if not docs:
            return
        self._db.aql.execute(
            """
            FOR doc IN @docs
                INSERT doc INTO @@collection
            """,
            bind_vars={"@collection": self.TAG_MODEL_OUTPUT_COLLECTION, "docs": docs},
        )

    def update_tag_model_output_edges_batch(self, docs: list[dict[str, Any]]) -> None:
        if not docs:
            return
        self._db.aql.execute(
            """
            FOR doc IN @docs
                UPDATE doc IN @@collection
            """,
            bind_vars={"@collection": self.TAG_MODEL_OUTPUT_COLLECTION, "docs": docs},
        )

    def delete_tag_model_outputs_for_model(self, model_id: str) -> None:
        self._db.aql.execute(
            """
            LET output_ids = (
                FOR edge IN @@model_output_edges
                    FILTER edge._from == @model_id
                    RETURN edge._to
            )
            FOR edge IN @@tag_output_edges
                FILTER edge._to IN output_ids
                REMOVE edge IN @@tag_output_edges
            """,
            bind_vars={
                "@model_output_edges": self.MODEL_OUTPUT_EDGE_COLLECTION,
                "@tag_output_edges": self.TAG_MODEL_OUTPUT_COLLECTION,
                "model_id": _as_document_id(self.MODEL_COLLECTION, model_id),
            },
        )

    def delete_tag_model_output_edges_for_tag(self, tag_id: str) -> int:
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._from == @tag_id
                REMOVE edge IN @@collection
                RETURN 1
            """,
            bind_vars={
                "@collection": self.TAG_MODEL_OUTPUT_COLLECTION,
                "tag_id": _as_document_id(self.TAG_COLLECTION, tag_id),
            },
        )
        return len(list(cursor))

    def count_tag_model_output_edges_for_tag(self, tag_id: str) -> int:
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._from == @tag_id
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={
                "@collection": self.TAG_MODEL_OUTPUT_COLLECTION,
                "tag_id": _as_document_id(self.TAG_COLLECTION, tag_id),
            },
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def delete_tag_model_output_edges_for_outputs(self, output_ids: list[str]) -> int:
        normalized_output_ids = [_as_document_id(self.MODEL_OUTPUT_COLLECTION, output_id) for output_id in output_ids]
        if not normalized_output_ids:
            return 0
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._to IN @output_ids
                REMOVE edge IN @@collection
                RETURN 1
            """,
            bind_vars={"@collection": self.TAG_MODEL_OUTPUT_COLLECTION, "output_ids": normalized_output_ids},
        )
        return len(list(cursor))

    def get_calibration_state(self, model_id: str) -> Document | None:
        results = primitives.execute(
            self._db,
            """
            FOR edge IN @@edge_collection
                FILTER edge._from == @model_id
                LET calibration = DOCUMENT(edge._to)
                FILTER calibration != null
                LIMIT 1
                RETURN calibration
            """,
            {
                "@edge_collection": self.CALIBRATION_EDGE_COLLECTION,
                "model_id": _as_document_id(self.MODEL_COLLECTION, model_id),
            },
        )
        return results[0] if results else None

    def get_calibration_state_doc(self, head_name: str, label: str) -> Document | None:
        calibration_key = f"{head_name}_{label}"
        results = primitives.get_many_by_keys(self._db, self.CALIBRATION_COLLECTION, [calibration_key])
        return results[0] if results else None

    def list_calibration_states(self) -> list[Document]:
        return primitives.execute(
            self._db,
            """
            FOR doc IN @@collection
                SORT doc._key
                RETURN doc
            """,
            {"@collection": self.CALIBRATION_COLLECTION},
        )

    def get_model_has_calibration_edges_by_ids(self, edge_ids: list[str]) -> list[Document]:
        return primitives.get_many_by_keys(
            self._db,
            self.CALIBRATION_EDGE_COLLECTION,
            [_extract_key(edge_id) for edge_id in edge_ids],
        )

    def upsert_calibration_state(self, model_id: str, payload: dict[str, Any]) -> None:
        current = self.get_calibration_state(model_id)
        if current is None:
            calibration_id = primitives.insert_document(self._db, self.CALIBRATION_COLLECTION, payload)
        else:
            calibration_id = cast("str", current["_id"])
            primitives.update_document_by_key(
                self._db, self.CALIBRATION_COLLECTION, _extract_key(calibration_id), payload
            )
        self._upsert_edge(
            self.CALIBRATION_EDGE_COLLECTION,
            _as_document_id(self.MODEL_COLLECTION, model_id),
            calibration_id,
        )

    def upsert_calibration_state_doc(self, key: str, payload: dict[str, Any]) -> None:
        self._db.aql.execute(
            """
            UPSERT { _key: @calibration_key }
                INSERT MERGE(@payload, { _key: @calibration_key })
                UPDATE @payload
                IN @@collection
            """,
            bind_vars={
                "@collection": self.CALIBRATION_COLLECTION,
                "calibration_key": key,
                "payload": payload,
            },
        )

    def upsert_model_has_calibration_edge(self, key: str, model_id: str, calibration_state_id: str) -> None:
        self._db.aql.execute(
            """
            UPSERT { _key: @edge_key }
                INSERT { _key: @edge_key, _from: @model_id, _to: @calibration_id }
                UPDATE { _from: @model_id, _to: @calibration_id }
                IN @@collection
            """,
            bind_vars={
                "@collection": self.CALIBRATION_EDGE_COLLECTION,
                "edge_key": key,
                "model_id": _as_document_id(self.MODEL_COLLECTION, model_id),
                "calibration_id": _as_document_id(self.CALIBRATION_COLLECTION, calibration_state_id),
            },
        )

    def delete_calibration_state_doc(self, calibration_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.CALIBRATION_COLLECTION, [_extract_key(calibration_id)])

    def delete_model_has_calibration_edge(self, edge_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.CALIBRATION_EDGE_COLLECTION, [_extract_key(edge_id)])

    def truncate_calibration_states(self) -> None:
        self._truncate_collection(self.CALIBRATION_COLLECTION)

    def add_calibration_history(self, payload: dict[str, Any]) -> str:
        return primitives.insert_document(self._db, self.CALIBRATION_HISTORY_COLLECTION, payload)

    def get_calibration_history_snapshots(self, calibration_key: str) -> list[Document]:
        return primitives.execute(
            self._db,
            """
            FOR doc IN @@collection
                FILTER doc.calibration_key == @calibration_key
                SORT doc._key
                RETURN doc
            """,
            {"@collection": self.CALIBRATION_HISTORY_COLLECTION, "calibration_key": calibration_key},
        )

    def count_calibration_history(self, model_id: str) -> int:
        calibration = self.get_calibration_state(model_id)
        if calibration is None:
            return 0
        calibration_id = cast("str", calibration["_id"])
        calibration_key = _extract_key(calibration_id)
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER doc.calibration_key == @calibration_key OR doc.calibration_key == @calibration_id
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={
                "@collection": self.CALIBRATION_HISTORY_COLLECTION,
                "calibration_key": calibration_key,
                "calibration_id": calibration_id,
            },
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def delete_calibration_history_for_model(self, model_id: str) -> None:
        calibration = self.get_calibration_state(model_id)
        if calibration is None:
            return
        calibration_id = cast("str", calibration["_id"])
        calibration_key = _extract_key(calibration_id)
        self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER doc.calibration_key == @calibration_key OR doc.calibration_key == @calibration_id
                REMOVE doc IN @@collection
            """,
            bind_vars={
                "@collection": self.CALIBRATION_HISTORY_COLLECTION,
                "calibration_key": calibration_key,
                "calibration_id": calibration_id,
            },
        )

    def delete_calibration_history_entries(self, entry_ids: list[str]) -> None:
        if not entry_ids:
            return
        primitives.delete_many_by_keys(
            self._db,
            self.CALIBRATION_HISTORY_COLLECTION,
            [_extract_key(entry_id) for entry_id in entry_ids],
        )

    def truncate_calibration_history(self) -> None:
        self._truncate_collection(self.CALIBRATION_HISTORY_COLLECTION)

    def _upsert_edge(self, collection: str, from_id: str, to_id: str) -> None:
        self._db.aql.execute(
            """
            UPSERT { _from: @from_id, _to: @to_id }
                INSERT { _from: @from_id, _to: @to_id }
                UPDATE {}
                IN @@collection
            """,
            bind_vars={"@collection": collection, "from_id": from_id, "to_id": to_id},
        )

    def _truncate_collection(self, collection_name: str) -> None:
        self._db.aql.execute(
            """
            FOR doc IN @@collection
                REMOVE doc IN @@collection
            """,
            bind_vars={"@collection": collection_name},
        )
