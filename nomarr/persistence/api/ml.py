from __future__ import annotations

from typing import Any, cast

from nomarr.persistence.database.ml_models_aql import MlModelsAqlOperations
from nomarr.persistence.database.ml_streams_aql import MlStreamsAqlOperations
from nomarr.persistence.database.vectors_aql import VectorsAqlOperations
from nomarr.persistence.schema_types import VectorCollection


def _as_document_id(collection: str, doc_id_or_key: str) -> str:
    if "/" in doc_id_or_key:
        return doc_id_or_key
    return f"{collection}/{doc_id_or_key}"


def _document_key(doc_id_or_key: str) -> str:
    if "/" in doc_id_or_key:
        return doc_id_or_key.split("/", 1)[1]
    return doc_id_or_key


class MlMaintenanceDb:
    """Maintenance-only companion surface for ML persistence operations.

    Wired as ``MlDb.maintenance`` by Part A. Destructive, reset, repair,
    and diagnostics-only operations belong here, not on the routine top-level
    ``MlDb`` surface. Parts D/E add new maintenance methods here and clean
    up any remaining top-level shims.
    """

    def __init__(
        self,
        *,
        vectors: VectorsAqlOperations,
        models: MlModelsAqlOperations,
    ) -> None:
        self._vectors = vectors
        self._models = models

    def truncate_vectors_in_collection(self, collection_name: str) -> None:
        """Truncate all vectors stored in the given registered vector collection."""
        return self._vectors.truncate_vector_collection(collection_name)

    def truncate_vector_collection(self, collection_name: str) -> None:
        """Compatibility shim for `truncate_vectors_in_collection`; truncates all vectors in the collection."""
        return self.truncate_vectors_in_collection(collection_name)

    def truncate_vector_edges(self) -> None:
        """Truncate all file-to-vector edge documents."""
        return self._vectors.truncate_vector_edges()

    def truncate_calibration_states(self) -> None:
        """Truncate all calibration state documents."""
        return self._models.truncate_calibration_states()

    def truncate_calibration_history(self) -> None:
        """Truncate all calibration history documents."""
        return self._models.truncate_calibration_history()


class MlDb:
    """Persistence sub-facade for ML model, stream, and vector operations.

    Routine callers use the normalized ML intent methods on this facade.
    Maintenance operations live on ``.maintenance`` (an ``MlMaintenanceDb``
    instance) instead of the routine top-level API.
    """

    _MODEL_COLLECTION = "ml_models"
    _MODEL_OUTPUT_COLLECTION = "ml_model_outputs"
    _MODEL_OUTPUT_EDGE_COLLECTION = "model_has_output"
    _CALIBRATION_COLLECTION = "calibration_state"
    _CALIBRATION_EDGE_COLLECTION = "model_has_calibration"

    def __init__(
        self,
        *,
        streams: MlStreamsAqlOperations,
        vectors: VectorsAqlOperations,
        models: MlModelsAqlOperations,
    ) -> None:
        self._streams = streams
        self._vectors = vectors
        self._models = models
        self.maintenance: MlMaintenanceDb = MlMaintenanceDb(
            vectors=vectors,
            models=models,
        )

    # ------------------------------------------------------------------
    # Canonical routine top-level methods aligned with the DD contract
    # ------------------------------------------------------------------

    def add_vector_collection(self, name: str, template: str) -> VectorCollection:
        """Register a named vector collection from the given template."""
        return self._vectors.register_vector_collection(name, template)

    def list_vector_collection_names(self) -> list[str]:
        """Return all registered vector collection names."""
        return self._vectors.list_registered_vector_collection_names()

    def clear_vector_collection(self, collection_name: str) -> None:
        """Remove all vectors stored in the given registered vector collection."""
        return self.maintenance.truncate_vector_collection(collection_name)

    def clear_vector_links(self) -> None:
        """Remove all file-to-vector link records."""
        return self.maintenance.truncate_vector_edges()

    def list_vector_namespaces(self) -> dict[str, Any]:
        """Return all registered vector namespace mappings."""
        return self._vectors.list_registered_vector_namespaces()

    def list_output_streams_for_file(self, file_id: str) -> list[dict[str, Any]]:
        """Return all canonical output stream documents linked to one file."""
        return self._streams.get_output_streams_for_file(file_id)

    def list_file_vectors(self, collection_name: str, file_id: str) -> list[dict[str, Any]]:
        """Return all vector documents stored for one file in a collection."""
        return self._vectors.get_file_vectors(collection_name, file_id)

    def search_vectors(
        self,
        collection_name: str,
        query_vector: list[float],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return nearest-neighbour vectors for ``query_vector`` in ``collection_name``.

        Canonical caller entrypoint for vector similarity search; higher layers
        should use this method instead of the removed legacy ``vector_search``
        facade name.
        """
        return self._vectors.vector_search(collection_name, query_vector, limit=limit)

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        """Return the ml_models document for model_id, or None if absent."""
        return self._models.get_model(model_id)

    def get_model_by_path(self, path: str) -> dict[str, Any] | None:
        """Return the ml_models document whose path matches, or None."""
        return self._models.get_model_by_path(path)

    def add_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Upsert a model document and return the persisted ml_models document.

        Raises:
            RuntimeError: If the upsert succeeds but the persisted document cannot be reloaded.
        """
        self._models.upsert_model(payload)

        model_id = payload.get("_id")
        if isinstance(model_id, str) and model_id:
            model_doc = self._models.get_model(model_id)
            if model_doc is not None:
                return model_doc

        model_path = payload.get("path")
        if isinstance(model_path, str) and model_path:
            model_doc = self._models.get_model_by_path(model_path)
            if model_doc is not None:
                return model_doc

        model_key = payload.get("_key")
        if isinstance(model_key, str) and model_key:
            model_doc = self._models.get_model(_as_document_id(self._MODEL_COLLECTION, model_key))
            if model_doc is not None:
                return model_doc

        msg = "Model upsert succeeded but persisted model could not be reloaded"
        raise RuntimeError(msg)

    def update_model(self, model_id: str, fields: dict[str, Any]) -> None:
        """Apply field updates to an existing ml_models document."""
        payload = dict(fields)
        payload["_key"] = _document_key(model_id)
        self._models.upsert_model(payload)

    def remove_model(self, model_id: str) -> None:
        """Delete one ml_models document by _id."""
        return self._models.delete_model(model_id)

    def list_models(self) -> list[dict[str, Any]]:
        """Return all ml_models documents."""
        return self._models.list_models()

    def count_models(self) -> int:
        """Return the total number of registered ml_models documents."""
        return self._models.count_models()

    def list_models_by_ids(self, model_ids: list[str]) -> list[dict[str, Any]]:
        """Return ml_models documents whose _ids are in model_ids."""
        return self._models.get_models_by_ids(model_ids)

    def get_model_output(self, output_id: str) -> dict[str, Any] | None:
        """Return one ml_model_outputs document by _id, or None."""
        return self._models.get_model_output(output_id)

    def list_model_outputs(self, model_id: str) -> list[dict[str, Any]]:
        """Return all ml_model_outputs documents linked to one model, ordered by index."""
        return self._models.list_model_outputs(model_id)

    def get_calibration_state(self, model_id: str) -> dict[str, Any] | None:
        """Return the calibration_state document for model_id, or None."""
        return self._models.get_calibration_state(model_id)

    def get_calibration_state_view(self, head_name: str, label: str) -> dict[str, Any] | None:
        """Return a calibration_state document by logical (head_name, label) identity."""
        return self._models.get_calibration_state_doc(head_name, label)

    def list_calibration_states(self) -> list[dict[str, Any]]:
        """Return all calibration_state documents."""
        return self._models.list_calibration_states()

    def list_calibration_history_snapshots(self, calibration_key: str) -> list[dict[str, Any]]:
        """Return all calibration_history snapshot documents for one calibration key."""
        return self._models.get_calibration_history_snapshots(calibration_key)

    def add_calibration_history(self, payload: dict[str, Any]) -> str:
        """Insert a calibration_history snapshot and return its _id."""
        return self._models.add_calibration_history(payload)

    def count_calibration_history(self, model_id: str) -> int:
        """Return the number of calibration history entries for one model."""
        return self._models.count_calibration_history(model_id)

    # ------------------------------------------------------------------
    # Promoted intent-complete write methods
    # ------------------------------------------------------------------

    def replace_output_streams_for_file(
        self,
        file_id: str,
        stream_payloads: list[dict[str, Any]],
    ) -> None:
        """Replace all canonical output streams for one file (delete-then-insert)."""
        self._streams.delete_output_streams_for_file(file_id)
        if stream_payloads:
            self._streams.upsert_output_streams_batch(file_id, stream_payloads)

    def remove_output_streams_for_file(self, file_id: str) -> None:
        """Delete all canonical output streams linked to one file."""
        return self._streams.delete_output_streams_for_file(file_id)

    def replace_file_vectors(
        self,
        collection_name: str,
        file_id: str,
        vector_payloads: list[dict[str, Any]],
    ) -> None:
        """Replace all vector documents for one file in a collection (delete-then-insert)."""
        self._vectors.delete_vectors_for_file(collection_name, file_id)
        for payload in vector_payloads:
            vector_payload = dict(payload)
            vector_payload.setdefault("file_id", file_id)
            self._vectors.upsert_vector(collection_name, vector_payload)

    def remove_file_vectors(self, collection_name: str, file_id: str) -> None:
        """Delete all vector documents for one file in a collection."""
        return self._vectors.delete_vectors_for_file(collection_name, file_id)

    def remove_vectors_for_files(self, collection_name: str, file_ids: list[str]) -> None:
        """Delete all vector documents for each file_id in file_ids."""
        for file_id in file_ids:
            self.remove_file_vectors(collection_name, file_id)

    def replace_model_output(self, model_id: str, output_key: str, payload: dict[str, Any]) -> str:
        """Upsert one output vertex and ensure the model→output edge exists; returns the output _id."""
        output_id = _as_document_id(self._MODEL_OUTPUT_COLLECTION, output_key)
        existing_output = self._models.get_model_output(output_id)
        if existing_output is None:
            insert_payload = dict(payload)
            insert_payload.setdefault("_key", _document_key(output_key))
            output_id = self._models.add_model_output(insert_payload)
        else:
            self._models.update_model_output(output_id, payload)
            existing_output_id = existing_output.get("_id")
            if isinstance(existing_output_id, str) and existing_output_id:
                output_id = existing_output_id

        self._models.upsert_model_output_edge(_document_key(output_key), model_id, output_id)
        return output_id

    def remove_model_output(self, output_id: str) -> None:
        """Delete one output vertex and its associated edges."""
        normalized_output_id = _as_document_id(self._MODEL_OUTPUT_COLLECTION, output_id)
        self._delete_model_output_edge(normalized_output_id)
        self._models.delete_model_output(normalized_output_id)

    def remove_model_outputs_for_model(self, model_id: str) -> list[str]:
        """Delete all output vertices for one model and return their _ids."""
        output_ids = [
            cast("str", output_doc["_id"])
            for output_doc in self._models.list_model_outputs(model_id)
            if isinstance(output_doc.get("_id"), str)
        ]
        self._models.delete_model_outputs_for_model(model_id)
        return output_ids

    def list_all_calibration_states_with_models(self) -> list[dict[str, Any]]:
        """Return all calibration states enriched with their owning model metadata."""
        return self._models.list_calibration_states_with_models()

    def replace_calibration_state(self, model_id: str, key: str, payload: dict[str, Any]) -> None:
        """Upsert a calibration_state document and ensure the model→calibration edge."""
        calibration_payload = dict(payload)
        calibration_payload.setdefault("_key", key)
        self._models.upsert_calibration_state(model_id, calibration_payload)

    def remove_calibration_state(self, calibration_id: str) -> None:
        """Delete one calibration_state document and its model→calibration edge."""
        calibration_key = _document_key(calibration_id)
        self._models.delete_model_has_calibration_edge(
            _as_document_id(self._CALIBRATION_EDGE_COLLECTION, calibration_key)
        )
        self._models.delete_calibration_state_doc(calibration_id)

    def remove_calibration_history_for_model(self, model_id: str) -> None:
        """Delete all calibration history entries for one model."""
        return self._models.delete_calibration_history_for_model(model_id)

    def remove_calibration_history_entries(self, entry_ids: list[str]) -> None:
        """Delete calibration history documents by _id list."""
        return self._models.delete_calibration_history_entries(entry_ids)

    def get_embedding_stats(self, backbone_id: str, library_key: str) -> dict[str, int | bool]:
        """Return hot_count, cold_count, and index_exists for a backbone+library."""
        return self._vectors.get_embedding_stats(backbone_id, library_key)

    def has_embedding_index(self, backbone_id: str, library_key: str) -> bool:
        """Return True if the cold collection has an ANN vector index."""
        return self._vectors.has_embedding_index(backbone_id, library_key)

    def index_library_embeddings(
        self,
        backbone_id: str,
        library_key: str,
        embed_dim: int,
        nlists: int,
    ) -> int:
        """Drain hot vectors to cold and build the ANN index.

        Idempotent: no-op if hot is already empty and index exists.
        Returns number of documents drained.
        """
        return self._vectors.index_library_embeddings(
            backbone_id,
            library_key,
            embed_dim,
            nlists,
        )

    def rebuild_library_embedding_index(
        self,
        backbone_id: str,
        library_key: str,
        embed_dim: int,
        nlists: int,
    ) -> None:
        """Drop and rebuild the ANN index without draining hot."""
        return self._vectors.rebuild_library_embedding_index(
            backbone_id,
            library_key,
            embed_dim,
            nlists,
        )

    def _delete_model_output_edge(self, output_id: str) -> None:
        self._models.delete_model_output_edge(output_id)
