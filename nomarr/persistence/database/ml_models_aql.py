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

    def delete_model_output_edge(self, output_id: str) -> None:
        """Delete the model→output edge whose _key or _to matches output_id."""
        self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._key == @edge_key OR edge._to == @output_id
                REMOVE edge IN @@collection
            """,
            bind_vars={
                "@collection": self.MODEL_OUTPUT_EDGE_COLLECTION,
                "edge_key": _extract_key(output_id),
                "output_id": _as_document_id(self.MODEL_OUTPUT_COLLECTION, output_id),
            },
        )

    def delete_model_output(self, output_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.MODEL_OUTPUT_COLLECTION, [_extract_key(output_id)])

    def delete_model_outputs_for_model(self, model_id: str) -> list[str]:
        """Delete all output documents and their edges for a model.

        Collects output IDs via ``model_has_output`` edge traversal, then removes
        the output documents and the edge rows in a single multi-collection AQL pass.

        Args:
            model_id: Model document ID or ``_key``.

        Returns:
            List of output document IDs that were deleted.
        """
        # Part C keeps this handwritten because it removes model-output documents
        # together with their edge rows; that multi-collection graph cleanup stays Tier 2.
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

    def list_calibration_states_with_models(self) -> list[Document]:
        """Return all calibration states enriched with owning model metadata.

        Joins calibration_state documents with model_has_calibration edges and
        ml_models documents in a single AQL traversal. Results sorted by
        (head_name, label).
        """
        return primitives.execute(
            self._db,
            """
            FOR calibration IN @@calibration_collection
                LET edge = FIRST(
                    FOR e IN @@calibration_edge_collection
                        FILTER e._to == calibration._id
                        LIMIT 1
                        RETURN e
                )
                LET model = edge != null ? DOCUMENT(edge._from) : null
                SORT calibration.head_name, calibration.label
                RETURN MERGE(
                    calibration,
                    {
                        model: model == null ? null : {
                            backbone: model.backbone,
                            embedder_release_date: model.embedder_release_date
                        }
                    }
                )
            """,
            {
                "@calibration_collection": self.CALIBRATION_COLLECTION,
                "@calibration_edge_collection": self.CALIBRATION_EDGE_COLLECTION,
            },
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
