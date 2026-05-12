from __future__ import annotations

from typing import Any

from nomarr.persistence.database.ml_models_aql import MlModelsAqlOperations
from nomarr.persistence.database.ml_streams_aql import MlStreamsAqlOperations
from nomarr.persistence.database.vectors_aql import VectorsAqlOperations
from nomarr.persistence.schema_types import VectorCollection


class MlDb:
    """Persistence sub-facade for ML model, stream, and vector operations."""

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

    def register_vector_collection(self, name: str, template: str) -> VectorCollection:
        return self._vectors.register_vector_collection(name, template)

    def list_registered_vector_collection_names(self) -> list[str]:
        return self._vectors.list_registered_vector_collection_names()

    def list_registered_vector_namespaces(self) -> dict[str, Any]:
        return self._vectors.list_registered_vector_namespaces()

    def truncate_vector_collection(self, collection_name: str) -> None:
        return self._vectors.truncate_vector_collection(collection_name)

    def truncate_vector_edges(self) -> None:
        return self._vectors.truncate_vector_edges()

    def get_output_streams_for_file(self, file_id: str) -> list[dict]:
        return self._streams.get_output_streams_for_file(file_id)

    def upsert_output_streams_batch(self, file_id: str, stream_payloads: list[dict]) -> None:
        return self._streams.upsert_output_streams_batch(file_id, stream_payloads)

    def delete_output_streams_for_file(self, file_id: str) -> None:
        return self._streams.delete_output_streams_for_file(file_id)

    def get_file_vectors(self, collection_name: str, file_id: str) -> list[dict]:
        return self._vectors.get_file_vectors(collection_name, file_id)

    def upsert_vector(self, collection_name: str, payload: dict) -> None:
        return self._vectors.upsert_vector(collection_name, payload)

    def upsert_file_has_vector_edge(self, file_id: str, vector_id: str) -> None:
        return self._vectors.upsert_file_has_vector_edge(file_id, vector_id)

    def delete_vectors_for_file(self, collection_name: str, file_id: str) -> None:
        return self._vectors.delete_vectors_for_file(collection_name, file_id)

    def delete_file_has_vector_edges_for_file(self, file_id: str) -> int:
        return self._vectors.delete_file_has_vector_edges_for_file(file_id)

    def delete_file_has_vector_edges_for_files(self, file_ids: list[str]) -> int:
        return self._vectors.delete_file_has_vector_edges_for_files(file_ids)

    def vector_search(self, collection_name: str, query_vector: list[float], *, limit: int) -> list[dict]:
        return self._vectors.vector_search(collection_name, query_vector, limit=limit)

    def get_model(self, model_id: str) -> dict | None:
        return self._models.get_model(model_id)

    def get_model_by_path(self, path: str) -> dict | None:
        return self._models.get_model_by_path(path)

    def upsert_model(self, payload: dict) -> None:
        return self._models.upsert_model(payload)

    def delete_model(self, model_id: str) -> None:
        return self._models.delete_model(model_id)

    def list_models(self) -> list[dict]:
        return self._models.list_models()

    def count_models(self) -> int:
        return self._models.count_models()

    def get_models_by_ids(self, model_ids: list[str]) -> list[dict]:
        return self._models.get_models_by_ids(model_ids)

    def get_model_output(self, output_id: str) -> dict | None:
        return self._models.get_model_output(output_id)

    def list_model_outputs(self, model_id: str) -> list[dict]:
        return self._models.list_model_outputs(model_id)

    def add_model_output(self, payload: dict) -> str:
        return self._models.add_model_output(payload)

    def update_model_output(self, output_id: str, fields: dict) -> None:
        return self._models.update_model_output(output_id, fields)

    def upsert_model_output_edge(self, output_key: str, model_id: str, output_id: str) -> None:
        return self._models.upsert_model_output_edge(output_key, model_id, output_id)

    def delete_model_output(self, output_id: str) -> None:
        return self._models.delete_model_output(output_id)

    def get_tag_model_output(self, key: str) -> dict | None:
        return self._models.get_tag_model_output(key)

    def get_tag_model_output_edges_for_tags(self, tag_ids: list[str]) -> list[dict]:
        return self._models.get_tag_model_output_edges_for_tags(tag_ids)

    def upsert_tag_model_output(self, payload: dict) -> None:
        return self._models.upsert_tag_model_output(payload)

    def insert_tag_model_output_edges_batch(self, docs: list[dict]) -> None:
        return self._models.insert_tag_model_output_edges_batch(docs)

    def update_tag_model_output_edges_batch(self, docs: list[dict]) -> None:
        return self._models.update_tag_model_output_edges_batch(docs)

    def delete_tag_model_outputs_for_model(self, model_id: str) -> None:
        return self._models.delete_tag_model_outputs_for_model(model_id)

    def delete_model_outputs_for_model(self, model_id: str) -> list[str]:
        return self._models.delete_model_outputs_for_model(model_id)

    def delete_tag_model_output_edges_for_tag(self, tag_id: str) -> int:
        return self._models.delete_tag_model_output_edges_for_tag(tag_id)

    def count_tag_model_output_edges_for_tag(self, tag_id: str) -> int:
        return self._models.count_tag_model_output_edges_for_tag(tag_id)

    def delete_tag_model_output_edges_for_outputs(self, output_ids: list[str]) -> int:
        return self._models.delete_tag_model_output_edges_for_outputs(output_ids)

    def get_calibration_state(self, model_id: str) -> dict | None:
        return self._models.get_calibration_state(model_id)

    def get_calibration_state_doc(self, head_name: str, label: str) -> dict | None:
        return self._models.get_calibration_state_doc(head_name, label)

    def list_calibration_states(self) -> list[dict]:
        return self._models.list_calibration_states()

    def get_model_has_calibration_edges_by_ids(self, edge_ids: list[str]) -> list[dict]:
        return self._models.get_model_has_calibration_edges_by_ids(edge_ids)

    def upsert_calibration_state(self, model_id: str, payload: dict) -> None:
        return self._models.upsert_calibration_state(model_id, payload)

    def upsert_calibration_state_doc(self, key: str, payload: dict) -> None:
        return self._models.upsert_calibration_state_doc(key, payload)

    def upsert_model_has_calibration_edge(self, key: str, model_id: str, calibration_state_id: str) -> None:
        return self._models.upsert_model_has_calibration_edge(key, model_id, calibration_state_id)

    def delete_calibration_state_doc(self, calibration_id: str) -> None:
        return self._models.delete_calibration_state_doc(calibration_id)

    def delete_model_has_calibration_edge(self, edge_id: str) -> None:
        return self._models.delete_model_has_calibration_edge(edge_id)

    def truncate_calibration_states(self) -> None:
        return self._models.truncate_calibration_states()

    def add_calibration_history(self, payload: dict) -> str:
        return self._models.add_calibration_history(payload)

    def get_calibration_history_snapshots(self, calibration_key: str) -> list[dict]:
        return self._models.get_calibration_history_snapshots(calibration_key)

    def count_calibration_history(self, model_id: str) -> int:
        return self._models.count_calibration_history(model_id)

    def delete_calibration_history_for_model(self, model_id: str) -> None:
        return self._models.delete_calibration_history_for_model(model_id)

    def delete_calibration_history_entries(self, entry_ids: list[str]) -> None:
        return self._models.delete_calibration_history_entries(entry_ids)

    def truncate_calibration_history(self) -> None:
        return self._models.truncate_calibration_history()
