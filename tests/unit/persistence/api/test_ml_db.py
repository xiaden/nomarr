# mypy: disable-error-code=func-returns-value
"""Unit tests for ``MlDb`` delegation and contract shape."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, sentinel

import pytest

from nomarr.persistence.api.ml import MlDb, MlMaintenanceDb


def _make_ml_db() -> tuple[MlDb, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    vector_repo = MagicMock()
    model_repo = MagicMock()
    output_repo = MagicMock()
    calibration_repo = MagicMock()
    embedding_stream_repo = MagicMock()
    db = MlDb(
        vector_repo=vector_repo,
        model_repo=model_repo,
        output_repo=output_repo,
        calibration_repo=calibration_repo,
        embedding_stream_repo=embedding_stream_repo,
    )
    return db, vector_repo, model_repo, output_repo, calibration_repo, embedding_stream_repo


def _make_ml_maintenance_db() -> tuple[MlMaintenanceDb, MagicMock, MagicMock, MagicMock]:
    vector_repo = MagicMock()
    model_repo = MagicMock()
    calibration_repo = MagicMock()
    db = MlMaintenanceDb(
        vector_repo=vector_repo,
        model_repo=model_repo,
        calibration_repo=calibration_repo,
    )
    return db, vector_repo, model_repo, calibration_repo


@pytest.mark.unit
def test_exposes_ml_maintenance_surface() -> None:
    db, _, _, _, _, _ = _make_ml_db()

    assert isinstance(db.maintenance, MlMaintenanceDb)
    assert hasattr(db.maintenance, "truncate_vectors_in_collection")
    assert hasattr(db.maintenance, "truncate_calibration_states")
    assert hasattr(db.maintenance, "truncate_calibration_history")
    assert not hasattr(db.maintenance, "truncate_vector_edges")
    assert not hasattr(db, "truncate_vector_collection")
    assert not hasattr(db, "truncate_vector_edges")
    assert not hasattr(db, "truncate_calibration_states")
    assert not hasattr(db, "truncate_calibration_history")


@pytest.mark.unit
def test_removed_unsanctioned_raw_helpers_are_not_exposed() -> None:
    db, _, _, _, _, _ = _make_ml_db()

    assert not hasattr(db, "get_file_vectors")
    assert not hasattr(db, "upsert_vector")
    assert not hasattr(db, "delete_vectors_for_file")
    assert not hasattr(db, "delete_file_has_vector_edges_for_file")
    assert not hasattr(db, "delete_model_output")
    assert not hasattr(db, "upsert_calibration_state")
    assert not hasattr(db, "delete_calibration_history_for_model")
    assert not hasattr(db, "get_model_has_calibration_edges_by_ids")


@pytest.mark.unit
def test_add_vector_collection_removed() -> None:
    db, _, _, _, _, _ = _make_ml_db()

    assert not hasattr(db, "add_vector_collection"), (
        "add_vector_collection was removed — PostgreSQL uses a single embeddings table; "
        "no dynamic collection registration is needed"
    )


@pytest.mark.unit
def test_list_vector_collection_names_returns_embeddings() -> None:
    db, _, _, _, _, _ = _make_ml_db()

    result = db.list_vector_collection_names()

    assert result == ["embeddings"]


@pytest.mark.unit
def test_list_vector_namespaces_removed() -> None:
    db, _, _, _, _, _ = _make_ml_db()

    assert not hasattr(db, "list_vector_namespaces")


@pytest.mark.unit
def test_list_output_streams_for_file_delegates_to_output_repo() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.get_outputs_for_file = MagicMock(return_value=sentinel.result)

    result = db.list_output_streams_for_file(1)

    assert result is sentinel.result
    output_repo.get_outputs_for_file.assert_called_once_with(1)


@pytest.mark.unit
def test_list_file_vectors_delegates_to_vector_repo() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.get_embeddings_for_file = MagicMock(return_value=sentinel.result)

    result = db.list_file_vectors("vectors_track_hot__model__lib", 1)

    assert result is sentinel.result
    vector_repo.get_embeddings_for_file.assert_called_once_with(1)


@pytest.mark.unit
def test_search_vectors_delegates_to_vector_repo() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    query_vector = [0.1, 0.2]
    vector_repo.find_nearest = MagicMock(return_value=sentinel.result)

    result = db.search_vectors("openl3", query_vector, limit=5)

    assert result is sentinel.result
    vector_repo.find_nearest.assert_called_once_with(query_vector, backbone_id="openl3", limit=5)


@pytest.mark.unit
def test_get_model_delegates_to_model_repo() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.get_model = MagicMock(return_value=sentinel.result)

    result = db.get_model("model1")

    assert result is sentinel.result
    model_repo.get_model.assert_called_once_with("model1")


@pytest.mark.unit
def test_get_model_by_type_delegates_to_model_repo() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.get_model_by_type = MagicMock(return_value=sentinel.result)

    result = db.get_model_by_type("genre")

    assert result is sentinel.result
    model_repo.get_model_by_type.assert_called_once_with("genre")


@pytest.mark.unit
def test_add_model_upserts_via_model_repo() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    payload = {"model_type": "genre", "path": "models/foo.onnx"}
    model_repo.upsert_model = MagicMock(return_value=sentinel.result)

    result = db.add_model(payload)

    assert result is sentinel.result
    model_repo.upsert_model.assert_called_once_with(payload)


@pytest.mark.unit
def test_update_model_delegates_to_model_repo() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.update_model = MagicMock()

    db.update_model("model1", {"fully_configured": True})

    model_repo.update_model.assert_called_once_with("model1", {"fully_configured": True})


@pytest.mark.unit
def test_remove_model_delegates_to_model_repo() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.delete_model = MagicMock()

    db.remove_model("model1")

    model_repo.delete_model.assert_called_once_with("model1")


@pytest.mark.unit
def test_list_models_delegates_to_model_repo() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.list_models = MagicMock(return_value=sentinel.result)

    result = db.list_models()

    assert result is sentinel.result
    model_repo.list_models.assert_called_once_with()


@pytest.mark.unit
def test_count_models_delegates_to_model_repo() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.count_models = MagicMock(return_value=42)

    result = db.count_models()

    assert result == 42
    model_repo.count_models.assert_called_once_with()


@pytest.mark.unit
def test_list_models_by_ids_delegates_to_model_repo() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_ids = ["model1", "model2"]
    model_repo.get_models_by_ids = MagicMock(return_value=sentinel.result)

    result = db.list_models_by_ids(model_ids)

    assert result is sentinel.result
    model_repo.get_models_by_ids.assert_called_once_with(model_ids)


@pytest.mark.unit
def test_get_model_output_delegates_to_output_repo() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.get_output = MagicMock(return_value=sentinel.result)

    result = db.get_model_output(1)

    assert result is sentinel.result
    output_repo.get_output.assert_called_once_with(1)


@pytest.mark.unit
def test_list_model_outputs_delegates_to_output_repo() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.list_model_outputs = MagicMock(return_value=sentinel.result)

    result = db.list_model_outputs("model1")

    assert result is sentinel.result
    output_repo.list_model_outputs.assert_called_once_with("model1")


@pytest.mark.unit
def test_get_calibration_state_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.get_state = MagicMock(return_value=sentinel.result)

    result = db.get_calibration_state("model1")

    assert result is sentinel.result
    calibration_repo.get_state.assert_called_once_with("model1")


@pytest.mark.unit
def test_list_calibration_states_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.list_states = MagicMock(return_value=sentinel.result)

    result = db.list_calibration_states()

    assert result is sentinel.result
    calibration_repo.list_states.assert_called_once_with()


@pytest.mark.unit
def test_truncate_vectors_in_collection_delegates_to_vector_repo() -> None:
    db, vector_repo, _, _ = _make_ml_maintenance_db()
    vector_repo.truncate_embeddings = MagicMock()

    db.truncate_vectors_in_collection("vectors_track_hot__model__lib")

    vector_repo.truncate_embeddings.assert_called_once_with()


@pytest.mark.unit
def test_truncate_vector_collection_delegates_to_truncate_vectors() -> None:
    db, vector_repo, _, _ = _make_ml_maintenance_db()
    vector_repo.truncate_embeddings = MagicMock()

    db.truncate_vector_collection("vectors_track_hot__model__lib")

    vector_repo.truncate_embeddings.assert_called_once_with()


@pytest.mark.unit
def test_truncate_calibration_states_delegates_to_calibration_repo() -> None:
    db, _, _, calibration_repo = _make_ml_maintenance_db()
    calibration_repo.truncate_states = MagicMock()

    db.truncate_calibration_states()

    calibration_repo.truncate_states.assert_called_once_with()


@pytest.mark.unit
def test_truncate_calibration_history_delegates_to_calibration_repo() -> None:
    db, _, _, calibration_repo = _make_ml_maintenance_db()
    calibration_repo.truncate_history = MagicMock()

    db.truncate_calibration_history()

    calibration_repo.truncate_history.assert_called_once_with()


# ---------------------------------------------------------------------------
# Tests for high-risk untested MlDb methods (PostgreSQL rewrite coverage)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_replace_file_vectors_deletes_then_inserts_per_payload() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.delete_embeddings_for_file = MagicMock()
    vector_repo.insert_embedding = MagicMock()
    payloads: list[dict[str, Any]] = [
        {
            "backbone_id": "openl3",
            "model_id": "model_a",
            "embedding_vector": [0.1, 0.2, 0.3],
            "genres": ["rock"],
        },
        {
            "backbone_id": "openl3",
            "model_id": "model_b",
            "embedding_vector": [0.4, 0.5],
            "genres": None,
        },
    ]

    db.replace_file_vectors("vectors_track_hot__model__lib", 42, payloads)

    vector_repo.delete_embeddings_for_file.assert_called_once_with(42)
    assert vector_repo.insert_embedding.call_count == 2
    vector_repo.insert_embedding.assert_any_call(
        file_id=42,
        backbone_id="openl3",
        model_id="model_a",
        embedding_vector=[0.1, 0.2, 0.3],
        genres=["rock"],
    )
    vector_repo.insert_embedding.assert_any_call(
        file_id=42,
        backbone_id="openl3",
        model_id="model_b",
        embedding_vector=[0.4, 0.5],
        genres=None,
    )


@pytest.mark.unit
def test_replace_file_vectors_backbone_id_falls_back_to_collection_name() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.delete_embeddings_for_file = MagicMock()
    vector_repo.insert_embedding = MagicMock()
    payloads = [{"model_id": "model_a", "embedding_vector": [0.1]}]

    db.replace_file_vectors("openl3", 7, payloads)

    vector_repo.insert_embedding.assert_called_once_with(
        file_id=7,
        backbone_id="openl3",
        model_id="model_a",
        embedding_vector=[0.1],
        genres=None,
    )


@pytest.mark.unit
def test_replace_file_vectors_embedding_vector_falls_back_to_embedding_key() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.delete_embeddings_for_file = MagicMock()
    vector_repo.insert_embedding = MagicMock()
    payloads = [
        {
            "backbone_id": "openl3",
            "model_id": "model_a",
            "embedding": [0.9, 0.8],
        },
    ]

    db.replace_file_vectors("vectors_track_hot__model__lib", 1, payloads)

    vector_repo.insert_embedding.assert_called_once_with(
        file_id=1,
        backbone_id="openl3",
        model_id="model_a",
        embedding_vector=[0.9, 0.8],
        genres=None,
    )


@pytest.mark.unit
def test_replace_file_vectors_empty_payloads_only_deletes() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.delete_embeddings_for_file = MagicMock()
    vector_repo.insert_embedding = MagicMock()

    db.replace_file_vectors("openl3", 5, [])

    vector_repo.delete_embeddings_for_file.assert_called_once_with(5)
    vector_repo.insert_embedding.assert_not_called()


@pytest.mark.unit
def test_replace_output_streams_for_file_deletes_then_inserts_per_payload() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.delete_outputs_for_file = MagicMock()
    output_repo.store_output_stream = MagicMock()
    payloads = [
        {"model_id": "model_a", "status": "success"},
        {"model_id": "model_b", "status": "failed"},
    ]

    db.replace_output_streams_for_file(42, payloads)

    output_repo.delete_outputs_for_file.assert_called_once_with(42)
    assert output_repo.store_output_stream.call_count == 2
    output_repo.store_output_stream.assert_any_call(
        file_id=42,
        model_id="model_a",
        status="success",
    )
    output_repo.store_output_stream.assert_any_call(
        file_id=42,
        model_id="model_b",
        status="failed",
    )


@pytest.mark.unit
def test_replace_output_streams_for_file_empty_payloads_only_deletes() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.delete_outputs_for_file = MagicMock()
    output_repo.store_output_stream = MagicMock()

    db.replace_output_streams_for_file(10, [])

    output_repo.delete_outputs_for_file.assert_called_once_with(10)
    output_repo.store_output_stream.assert_not_called()


@pytest.mark.unit
def test_get_calibration_state_view_returns_matching_state() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    state_a = {"state_data": {"head_name": "genre", "label": "rock"}, "id": 1}
    state_b = {"state_data": {"head_name": "mood", "label": "happy"}, "id": 2}
    calibration_repo.list_states = MagicMock(return_value=[state_a, state_b])

    result = db.get_calibration_state_view("mood", "happy")

    assert result is state_b


@pytest.mark.unit
def test_get_calibration_state_view_returns_none_when_no_match() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    state_a = {"state_data": {"head_name": "genre", "label": "rock"}, "id": 1}
    calibration_repo.list_states = MagicMock(return_value=[state_a])

    result = db.get_calibration_state_view("mood", "happy")

    assert result is None


@pytest.mark.unit
def test_get_calibration_state_view_returns_none_for_empty_list() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.list_states = MagicMock(return_value=[])

    result = db.get_calibration_state_view("genre", "rock")

    assert result is None


@pytest.mark.unit
def test_add_calibration_history_unpacks_payload() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.record_history = MagicMock(return_value=sentinel.history_record)
    payload = {"model_id": "model1", "event": "calibrated", "data": {"accuracy": 0.95}}

    result = db.add_calibration_history(payload)

    assert result is sentinel.history_record
    calibration_repo.record_history.assert_called_once_with(
        model_id="model1",
        event="calibrated",
        data={"accuracy": 0.95},
    )


@pytest.mark.unit
def test_add_calibration_history_defaults_data_to_empty_dict() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.record_history = MagicMock(return_value=sentinel.history_record)
    payload = {"model_id": "model1", "event": "reset"}

    result = db.add_calibration_history(payload)

    assert result is sentinel.history_record
    calibration_repo.record_history.assert_called_once_with(
        model_id="model1",
        event="reset",
        data={},
    )


@pytest.mark.unit
def test_clear_vector_collection_delegates_to_delete_all_embeddings() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.delete_all_embeddings = MagicMock()

    db.clear_vector_collection("vectors_track_hot__model__lib")

    vector_repo.delete_all_embeddings.assert_called_once_with()


@pytest.mark.unit
def test_remove_vectors_for_files_deletes_each_file_id() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.delete_embeddings_for_file = MagicMock()

    db.remove_vectors_for_files("openl3", [10, 20, 30])

    assert vector_repo.delete_embeddings_for_file.call_count == 3
    vector_repo.delete_embeddings_for_file.assert_any_call(10)
    vector_repo.delete_embeddings_for_file.assert_any_call(20)
    vector_repo.delete_embeddings_for_file.assert_any_call(30)


@pytest.mark.unit
def test_remove_vectors_for_files_empty_list_makes_no_calls() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.delete_embeddings_for_file = MagicMock()

    db.remove_vectors_for_files("openl3", [])

    vector_repo.delete_embeddings_for_file.assert_not_called()


@pytest.mark.unit
def test_index_backbone_embeddings_delegates_to_drain_hot_to_cold() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.drain_hot_to_cold = MagicMock(return_value=17)

    result = db.index_backbone_embeddings("openl3")

    assert result == 17
    vector_repo.drain_hot_to_cold.assert_called_once_with("openl3")


@pytest.mark.unit
def test_index_backbone_embeddings_ignores_extra_args() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.drain_hot_to_cold = MagicMock(return_value=5)

    result = db.index_backbone_embeddings("openl3", embed_dim=128, nlists=100)

    assert result == 5
    vector_repo.drain_hot_to_cold.assert_called_once_with("openl3")


@pytest.mark.unit
def test_count_calibration_history_returns_length() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.get_history = MagicMock(return_value=[sentinel.h1, sentinel.h2, sentinel.h3])

    result = db.count_calibration_history("model1")

    assert result == 3
    calibration_repo.get_history.assert_called_once_with("model1")


@pytest.mark.unit
def test_count_calibration_history_returns_zero_for_empty() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.get_history = MagicMock(return_value=[])

    result = db.count_calibration_history("model1")

    assert result == 0
    calibration_repo.get_history.assert_called_once_with("model1")


# ---------------------------------------------------------------------------
# Group 1: Embedding Stream Operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_replace_embedding_stream_for_file_delegates_to_embedding_stream_repo() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.upsert_stream = MagicMock(return_value=sentinel.result)
    payload = {"status": "success", "frame_count": 100}

    result = db.replace_embedding_stream_for_file(42, "openl3", payload)

    assert result is sentinel.result
    embedding_stream_repo.upsert_stream.assert_called_once_with(42, "openl3", payload)


@pytest.mark.unit
def test_get_embedding_stream_for_file_delegates_to_embedding_stream_repo() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.get_stream = MagicMock(return_value=sentinel.result)

    result = db.get_embedding_stream_for_file(42, "openl3")

    assert result is sentinel.result
    embedding_stream_repo.get_stream.assert_called_once_with(42, "openl3")


@pytest.mark.unit
def test_get_embedding_stream_for_file_returns_none_when_absent() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.get_stream = MagicMock(return_value=None)

    result = db.get_embedding_stream_for_file(99, "openl3")

    assert result is None
    embedding_stream_repo.get_stream.assert_called_once_with(99, "openl3")


@pytest.mark.unit
def test_list_embedding_streams_by_backbone_default_params() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.list_by_backbone = MagicMock(return_value=sentinel.result)

    result = db.list_embedding_streams_by_backbone("openl3")

    assert result is sentinel.result
    embedding_stream_repo.list_by_backbone.assert_called_once_with("openl3", limit=50, offset=0)


@pytest.mark.unit
def test_list_embedding_streams_by_backbone_custom_pagination() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.list_by_backbone = MagicMock(return_value=sentinel.result)

    result = db.list_embedding_streams_by_backbone("openl3", limit=10, offset=20)

    assert result is sentinel.result
    embedding_stream_repo.list_by_backbone.assert_called_once_with("openl3", limit=10, offset=20)


@pytest.mark.unit
def test_remove_embedding_streams_for_file_delegates_to_embedding_stream_repo() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.delete_for_file = MagicMock()

    db.remove_embedding_streams_for_file(42)

    embedding_stream_repo.delete_for_file.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# Group 2: Output Operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_replace_model_output_delegates_to_output_repo_ignoring_output_key() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.store_model_output = MagicMock(return_value=sentinel.result)
    payload = {"genre": "rock", "confidence": 0.95}

    result = db.replace_model_output(42, "model1", "legacy_key", payload)

    assert result is sentinel.result
    output_repo.store_model_output.assert_called_once_with(
        file_id=42,
        model_id="model1",
        output_data=payload,
    )


@pytest.mark.unit
def test_remove_model_output_delegates_to_output_repo() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.delete_output = MagicMock()

    db.remove_model_output(7)

    output_repo.delete_output.assert_called_once_with(7)


@pytest.mark.unit
def test_remove_model_outputs_for_model_delegates_to_output_repo() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.delete_outputs_for_model = MagicMock(return_value=5)

    result = db.remove_model_outputs_for_model("model1")

    assert result == 5
    output_repo.delete_outputs_for_model.assert_called_once_with("model1")


# ---------------------------------------------------------------------------
# Group 3: Calibration State Operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_all_calibration_states_with_models_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.list_states_with_models = MagicMock(return_value=sentinel.result)

    result = db.list_all_calibration_states_with_models()

    assert result is sentinel.result
    calibration_repo.list_states_with_models.assert_called_once_with()


@pytest.mark.unit
def test_replace_calibration_state_delegates_to_calibration_repo_ignoring_key() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.set_state = MagicMock(return_value=sentinel.result)
    payload = {"head_name": "genre", "label": "rock"}

    result = db.replace_calibration_state("model1", "legacy_key", payload)

    assert result is sentinel.result
    calibration_repo.set_state.assert_called_once_with("model1", state_data=payload)


@pytest.mark.unit
def test_remove_calibration_state_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.delete_state = MagicMock()

    db.remove_calibration_state(3)

    calibration_repo.delete_state.assert_called_once_with(3)


# ---------------------------------------------------------------------------
# Group 4: Vector Operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_remove_file_vectors_delegates_to_vector_repo_ignoring_collection_name() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.delete_embeddings_for_file = MagicMock()

    db.remove_file_vectors("vectors_track_hot__model__lib", 42)

    vector_repo.delete_embeddings_for_file.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# Group 5: Calibration History
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_calibration_history_snapshots_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.get_history = MagicMock(return_value=sentinel.result)

    result = db.list_calibration_history_snapshots("model1")

    assert result is sentinel.result
    calibration_repo.get_history.assert_called_once_with("model1")


# ---------------------------------------------------------------------------
# Group 6: Formerly-NotImplemented methods (now delegated in PostgreSQL)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_remove_calibration_history_for_model_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.delete_history_for_model = MagicMock()

    db.remove_calibration_history_for_model("model1")

    calibration_repo.delete_history_for_model.assert_called_once_with("model1")


@pytest.mark.unit
def test_remove_calibration_history_entries_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.delete_history_entries = MagicMock()

    db.remove_calibration_history_entries([1, 2])

    # Entry IDs are converted from str to int before delegation
    calibration_repo.delete_history_entries.assert_called_once_with([1, 2])


@pytest.mark.unit
def test_rebuild_backbone_embedding_index_succeeds_silently() -> None:
    db, _, _, _, _, _ = _make_ml_db()

    # PostgreSQL manages the HNSW index automatically — the method
    # accepts embed_dim/nlists for backwards compatibility but should
    # not raise.
    db.rebuild_backbone_embedding_index("openl3", embed_dim=128, nlists=100)


# ---------------------------------------------------------------------------
# Group 7: Embedding Stats
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_embedding_stats_delegates_to_vector_repo() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.get_embedding_stats = MagicMock(return_value=sentinel.result)

    result = db.get_embedding_stats("openl3")

    assert result is sentinel.result
    vector_repo.get_embedding_stats.assert_called_once_with("openl3")
