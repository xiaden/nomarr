# mypy: disable-error-code=func-returns-value
"""Unit tests for ``MlDb`` delegation and contract shape."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, sentinel

import pytest

from nomarr.persistence.api.ml import MlDb, MlMaintenanceDb


def _make_ml_db() -> tuple[MlDb, MagicMock, MagicMock, MagicMock]:
    streams = MagicMock()
    vectors = MagicMock()
    models = MagicMock()
    db = MlDb(streams=streams, vectors=vectors, models=models)
    return db, streams, vectors, models


def _make_ml_maintenance_db() -> tuple[MlMaintenanceDb, MagicMock, MagicMock]:
    vectors = MagicMock()
    models = MagicMock()
    db = MlMaintenanceDb(vectors=vectors, models=models)
    return db, vectors, models


@pytest.mark.unit
def test_exposes_ml_maintenance_surface() -> None:
    db, _, _, _ = _make_ml_db()

    assert isinstance(db.maintenance, MlMaintenanceDb)
    assert hasattr(db.maintenance, "truncate_vectors_in_collection")
    assert hasattr(db.maintenance, "truncate_vector_edges")
    assert hasattr(db.maintenance, "truncate_calibration_states")
    assert hasattr(db.maintenance, "truncate_calibration_history")
    assert not hasattr(db, "truncate_vector_collection")
    assert not hasattr(db, "truncate_vector_edges")
    assert not hasattr(db, "truncate_calibration_states")
    assert not hasattr(db, "truncate_calibration_history")


@pytest.mark.unit
def test_removed_unsanctioned_raw_helpers_are_not_exposed() -> None:
    db, _, _, _ = _make_ml_db()

    assert not hasattr(db, "get_file_vectors")
    assert not hasattr(db, "upsert_vector")
    assert not hasattr(db, "delete_vectors_for_file")
    assert not hasattr(db, "delete_file_has_vector_edges_for_file")
    assert not hasattr(db, "delete_model_output")
    assert not hasattr(db, "upsert_calibration_state")
    assert not hasattr(db, "delete_calibration_history_for_model")
    assert not hasattr(db, "get_model_has_calibration_edges_by_ids")


@pytest.mark.unit
def test_add_vector_collection_delegates_to_vectors() -> None:
    db, _, vectors, _ = _make_ml_db()
    vectors.register_vector_collection.return_value = sentinel.result

    result = db.add_vector_collection("vectors_track_hot__model__lib", "vectors_track_hot")

    assert result is sentinel.result
    vectors.register_vector_collection.assert_called_once_with(
        "vectors_track_hot__model__lib",
        "vectors_track_hot",
    )


@pytest.mark.unit
def test_list_vector_collection_names_delegates_to_vectors() -> None:
    db, _, vectors, _ = _make_ml_db()
    vectors.list_registered_vector_collection_names.return_value = sentinel.result

    result = db.list_vector_collection_names()

    assert result is sentinel.result
    vectors.list_registered_vector_collection_names.assert_called_once_with()


@pytest.mark.unit
def test_list_vector_namespaces_delegates_to_vectors() -> None:
    db, _, vectors, _ = _make_ml_db()
    vectors.list_registered_vector_namespaces.return_value = sentinel.result

    result = db.list_vector_namespaces()

    assert result is sentinel.result
    vectors.list_registered_vector_namespaces.assert_called_once_with()


@pytest.mark.unit
def test_list_output_streams_for_file_delegates_to_streams() -> None:
    db, streams, _, _ = _make_ml_db()
    streams.get_output_streams_for_file.return_value = sentinel.result

    result = db.list_output_streams_for_file("library_files/1")

    assert result is sentinel.result
    streams.get_output_streams_for_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_list_file_vectors_delegates_to_vectors() -> None:
    db, _, vectors, _ = _make_ml_db()
    vectors.get_file_vectors.return_value = sentinel.result

    result = db.list_file_vectors("vectors_track_hot__model__lib", "library_files/1")

    assert result is sentinel.result
    vectors.get_file_vectors.assert_called_once_with("vectors_track_hot__model__lib", "library_files/1")


@pytest.mark.unit
def test_search_vectors_delegates_to_vectors() -> None:
    db, _, vectors, _ = _make_ml_db()
    query_vector = [0.1, 0.2]
    vectors.vector_search.return_value = sentinel.result

    result = db.search_vectors("vectors_track_hot__model__lib", query_vector, limit=5)

    assert result is sentinel.result
    vectors.vector_search.assert_called_once_with("vectors_track_hot__model__lib", query_vector, limit=5)


@pytest.mark.unit
def test_get_model_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.get_model.return_value = sentinel.result

    result = db.get_model("ml_models/1")

    assert result is sentinel.result
    models.get_model.assert_called_once_with("ml_models/1")


@pytest.mark.unit
def test_get_model_by_path_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.get_model_by_path.return_value = sentinel.result

    result = db.get_model_by_path("models/foo.onnx")

    assert result is sentinel.result
    models.get_model_by_path.assert_called_once_with("models/foo.onnx")


@pytest.mark.unit
def test_add_model_upserts_and_reloads_by_path() -> None:
    db, _, _, models = _make_ml_db()
    payload = {"_key": "model1", "path": "models/foo.onnx"}
    models.get_model_by_path.return_value = sentinel.result

    result = db.add_model(payload)

    assert result is sentinel.result
    models.upsert_model.assert_called_once_with(payload)
    models.get_model_by_path.assert_called_once_with("models/foo.onnx")


@pytest.mark.unit
def test_update_model_upserts_fields_by_model_key() -> None:
    db, _, _, models = _make_ml_db()

    db.update_model("ml_models/abc123", {"fully_configured": True})

    models.upsert_model.assert_called_once_with({"fully_configured": True, "_key": "abc123"})


@pytest.mark.unit
def test_remove_model_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.delete_model.return_value = sentinel.result

    result = db.remove_model("ml_models/1")

    assert result is sentinel.result
    models.delete_model.assert_called_once_with("ml_models/1")


@pytest.mark.unit
def test_list_models_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.list_models.return_value = sentinel.result

    result = db.list_models()

    assert result is sentinel.result
    models.list_models.assert_called_once_with()


@pytest.mark.unit
def test_count_models_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.count_models.return_value = sentinel.result

    result = db.count_models()

    assert result is sentinel.result
    models.count_models.assert_called_once_with()


@pytest.mark.unit
def test_list_models_by_ids_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    model_ids = ["ml_models/1", "ml_models/2"]
    models.get_models_by_ids.return_value = sentinel.result

    result = db.list_models_by_ids(model_ids)

    assert result is sentinel.result
    models.get_models_by_ids.assert_called_once_with(model_ids)


@pytest.mark.unit
def test_get_model_output_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.get_model_output.return_value = sentinel.result

    result = db.get_model_output("ml_model_outputs/1")

    assert result is sentinel.result
    models.get_model_output.assert_called_once_with("ml_model_outputs/1")


@pytest.mark.unit
def test_list_model_outputs_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.list_model_outputs.return_value = sentinel.result

    result = db.list_model_outputs("ml_models/1")

    assert result is sentinel.result
    models.list_model_outputs.assert_called_once_with("ml_models/1")


@pytest.mark.unit
def test_get_calibration_state_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.get_calibration_state.return_value = sentinel.result

    result = db.get_calibration_state("ml_models/1")

    assert result is sentinel.result
    models.get_calibration_state.assert_called_once_with("ml_models/1")


@pytest.mark.unit
def test_get_calibration_state_view_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.get_calibration_state_doc.return_value = sentinel.result

    result = db.get_calibration_state_view("mood_happy", "happy")

    assert result is sentinel.result
    models.get_calibration_state_doc.assert_called_once_with("mood_happy", "happy")


@pytest.mark.unit
def test_list_calibration_states_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.list_calibration_states.return_value = sentinel.result

    result = db.list_calibration_states()

    assert result is sentinel.result
    models.list_calibration_states.assert_called_once_with()


@pytest.mark.unit
def test_list_calibration_history_snapshots_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.get_calibration_history_snapshots.return_value = sentinel.result

    result = db.list_calibration_history_snapshots("mood_happy:happy")

    assert result is sentinel.result
    models.get_calibration_history_snapshots.assert_called_once_with("mood_happy:happy")


@pytest.mark.unit
def test_add_calibration_history_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    payload = {"model_id": "ml_models/1"}
    models.add_calibration_history.return_value = sentinel.result

    result = db.add_calibration_history(payload)

    assert result is sentinel.result
    models.add_calibration_history.assert_called_once_with(payload)


@pytest.mark.unit
def test_count_calibration_history_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.count_calibration_history.return_value = sentinel.result

    result = db.count_calibration_history("ml_models/1")

    assert result is sentinel.result
    models.count_calibration_history.assert_called_once_with("ml_models/1")


@pytest.mark.unit
def test_replace_output_streams_for_file_replaces_existing_streams() -> None:
    db, streams, _, _ = _make_ml_db()
    payloads = [{"output_id": "ml_model_outputs/1", "values": [0.1, 0.2]}]

    db.replace_output_streams_for_file("library_files/1", payloads)

    streams.delete_output_streams_for_file.assert_called_once_with("library_files/1")
    streams.upsert_output_streams_batch.assert_called_once_with("library_files/1", payloads)


@pytest.mark.unit
def test_replace_output_streams_for_file_skips_batch_write_when_empty() -> None:
    db, streams, _, _ = _make_ml_db()

    db.replace_output_streams_for_file("library_files/1", [])

    streams.delete_output_streams_for_file.assert_called_once_with("library_files/1")
    streams.upsert_output_streams_batch.assert_not_called()


@pytest.mark.unit
def test_remove_output_streams_for_file_delegates_to_streams() -> None:
    db, streams, _, _ = _make_ml_db()
    streams.delete_output_streams_for_file.return_value = sentinel.result

    result = db.remove_output_streams_for_file("library_files/1")

    assert result is sentinel.result
    streams.delete_output_streams_for_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_replace_file_vectors_removes_existing_and_upserts_new_payloads() -> None:
    db, _, vectors, _ = _make_ml_db()
    payloads = [{"_key": "vec1", "model_suite_hash": "suite1"}, {"_key": "vec2", "file_id": "library_files/1"}]

    db.replace_file_vectors("vectors_track_hot__model__lib", "library_files/1", payloads)

    vectors.delete_vectors_for_file.assert_called_once_with("vectors_track_hot__model__lib", "library_files/1")
    assert vectors.upsert_vector.call_count == 2
    vectors.upsert_vector.assert_any_call(
        "vectors_track_hot__model__lib",
        {"_key": "vec1", "model_suite_hash": "suite1", "file_id": "library_files/1"},
    )
    vectors.upsert_vector.assert_any_call(
        "vectors_track_hot__model__lib",
        {"_key": "vec2", "file_id": "library_files/1"},
    )


@pytest.mark.unit
def test_remove_file_vectors_delegates_to_vectors() -> None:
    db, _, vectors, _ = _make_ml_db()
    vectors.delete_vectors_for_file.return_value = sentinel.result

    result = db.remove_file_vectors("vectors_track_hot__model__lib", "library_files/1")

    assert result is sentinel.result
    vectors.delete_vectors_for_file.assert_called_once_with("vectors_track_hot__model__lib", "library_files/1")


@pytest.mark.unit
def test_remove_vectors_for_files_loops_over_each_file() -> None:
    db, _, _, _ = _make_ml_db()

    with patch.object(db, "remove_file_vectors") as remove_file_vectors:
        db.remove_vectors_for_files("vectors_track_hot__model__lib", ["library_files/1", "library_files/2"])

    assert remove_file_vectors.call_count == 2
    remove_file_vectors.assert_any_call("vectors_track_hot__model__lib", "library_files/1")
    remove_file_vectors.assert_any_call("vectors_track_hot__model__lib", "library_files/2")


@pytest.mark.unit
def test_replace_model_output_inserts_missing_doc_and_edge() -> None:
    db, _, _, models = _make_ml_db()
    models.get_model_output.return_value = None
    models.add_model_output.return_value = "ml_model_outputs/out1"

    result = db.replace_model_output(
        "ml_models/1",
        "out1",
        {"output_index": 0, "label": None, "fully_labeled": False},
    )

    assert result == "ml_model_outputs/out1"
    models.get_model_output.assert_called_once_with("ml_model_outputs/out1")
    models.add_model_output.assert_called_once_with(
        {"output_index": 0, "label": None, "fully_labeled": False, "_key": "out1"}
    )
    models.upsert_model_output_edge.assert_called_once_with("out1", "ml_models/1", "ml_model_outputs/out1")


@pytest.mark.unit
def test_replace_model_output_updates_existing_doc_and_edge() -> None:
    db, _, _, models = _make_ml_db()
    models.get_model_output.return_value = {"_id": "ml_model_outputs/out1"}

    result = db.replace_model_output("ml_models/1", "out1", {"label": "Happy", "fully_labeled": True})

    assert result == "ml_model_outputs/out1"
    models.update_model_output.assert_called_once_with(
        "ml_model_outputs/out1",
        {"label": "Happy", "fully_labeled": True},
    )
    models.upsert_model_output_edge.assert_called_once_with("out1", "ml_models/1", "ml_model_outputs/out1")


@pytest.mark.unit
def test_remove_model_output_deletes_model_edge_and_doc() -> None:
    db, _, _, models = _make_ml_db()

    with patch.object(db, "_delete_model_output_edge") as delete_edge:
        db.remove_model_output("out1")

    delete_edge.assert_called_once_with("ml_model_outputs/out1")
    models.delete_model_output.assert_called_once_with("ml_model_outputs/out1")


@pytest.mark.unit
def test_remove_model_outputs_for_model_collects_ids_and_bulk_deletes() -> None:
    db, _, _, models = _make_ml_db()
    models.list_model_outputs.return_value = [
        {"_id": "ml_model_outputs/out1"},
        {"_id": "ml_model_outputs/out2"},
    ]

    result = db.remove_model_outputs_for_model("ml_models/1")

    assert result == ["ml_model_outputs/out1", "ml_model_outputs/out2"]
    models.list_model_outputs.assert_called_once_with("ml_models/1")
    models.delete_model_outputs_for_model.assert_called_once_with("ml_models/1")


@pytest.mark.unit
def test_replace_calibration_state_delegates_to_models_with_key() -> None:
    db, _, _, models = _make_ml_db()

    db.replace_calibration_state("ml_models/1", "mood_happy:happy", {"p5": 0.1, "p95": 0.9})

    models.upsert_calibration_state.assert_called_once_with(
        "ml_models/1",
        {"p5": 0.1, "p95": 0.9, "_key": "mood_happy:happy"},
    )


@pytest.mark.unit
def test_remove_calibration_state_deletes_edge_and_doc() -> None:
    db, _, _, models = _make_ml_db()

    db.remove_calibration_state("calibration_state/mood_happy:happy")

    models.delete_model_has_calibration_edge.assert_called_once_with("model_has_calibration/mood_happy:happy")
    models.delete_calibration_state_doc.assert_called_once_with("calibration_state/mood_happy:happy")


@pytest.mark.unit
def test_remove_calibration_history_for_model_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.delete_calibration_history_for_model.return_value = sentinel.result

    result = db.remove_calibration_history_for_model("ml_models/1")

    assert result is sentinel.result
    models.delete_calibration_history_for_model.assert_called_once_with("ml_models/1")


@pytest.mark.unit
def test_remove_calibration_history_entries_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    entry_ids = ["calibration_history/1"]
    models.delete_calibration_history_entries.return_value = sentinel.result

    result = db.remove_calibration_history_entries(entry_ids)

    assert result is sentinel.result
    models.delete_calibration_history_entries.assert_called_once_with(entry_ids)


@pytest.mark.unit
def test_truncate_vectors_in_collection_delegates_to_vectors() -> None:
    db, vectors, _ = _make_ml_maintenance_db()
    vectors.truncate_vector_collection.return_value = sentinel.result

    result = db.truncate_vectors_in_collection("vectors_track_hot__model__lib")

    assert result is sentinel.result
    vectors.truncate_vector_collection.assert_called_once_with("vectors_track_hot__model__lib")


@pytest.mark.unit
def test_truncate_vector_collection_delegates_to_vectors() -> None:
    db, vectors, _ = _make_ml_maintenance_db()
    vectors.truncate_vector_collection.return_value = sentinel.result

    result = db.truncate_vector_collection("vectors_track_hot__model__lib")

    assert result is sentinel.result
    vectors.truncate_vector_collection.assert_called_once_with("vectors_track_hot__model__lib")


@pytest.mark.unit
def test_truncate_vector_edges_delegates_to_vectors() -> None:
    db, vectors, _ = _make_ml_maintenance_db()
    vectors.truncate_vector_edges.return_value = sentinel.result

    result = db.truncate_vector_edges()

    assert result is sentinel.result
    vectors.truncate_vector_edges.assert_called_once_with()


@pytest.mark.unit
def test_truncate_calibration_states_delegates_to_models() -> None:
    db, _, models = _make_ml_maintenance_db()
    models.truncate_calibration_states.return_value = sentinel.result

    result = db.truncate_calibration_states()

    assert result is sentinel.result
    models.truncate_calibration_states.assert_called_once_with()


@pytest.mark.unit
def test_truncate_calibration_history_delegates_to_models() -> None:
    db, _, models = _make_ml_maintenance_db()
    models.truncate_calibration_history.return_value = sentinel.result

    result = db.truncate_calibration_history()

    assert result is sentinel.result
    models.truncate_calibration_history.assert_called_once_with()


@pytest.mark.unit
def test_list_all_calibration_states_with_models_delegates_to_canonical_tier2_helper() -> None:
    db, _, _, models = _make_ml_db()
    models.list_calibration_states_with_models.return_value = []

    result = db.list_all_calibration_states_with_models()

    assert result == []
    models.list_calibration_states_with_models.assert_called_once_with()


@pytest.mark.unit
def test_list_all_calibration_states_with_models_returns_canonical_tier2_result() -> None:
    db, _, _, models = _make_ml_db()
    models.list_calibration_states_with_models.return_value = [
        {
            "_key": "edge-a",
            "head_name": "a_head",
            "label": "alpha",
            "value": 1,
            "model": {
                "backbone": "openl3",
                "embedder_release_date": "2024-06-01",
            },
        },
        {
            "_key": "edge-c",
            "head_name": "m_head",
            "label": "mid",
            "value": 3,
            "model": None,
        },
    ]

    result = db.list_all_calibration_states_with_models()

    assert result == [
        {
            "_key": "edge-a",
            "head_name": "a_head",
            "label": "alpha",
            "value": 1,
            "model": {
                "backbone": "openl3",
                "embedder_release_date": "2024-06-01",
            },
        },
        {
            "_key": "edge-c",
            "head_name": "m_head",
            "label": "mid",
            "value": 3,
            "model": None,
        },
    ]
    models.list_calibration_states_with_models.assert_called_once_with()


@pytest.mark.unit
def test_delete_model_output_edge_helper_delegates_to_canonical_tier2_helper() -> None:
    db, _, _, models = _make_ml_db()

    db._delete_model_output_edge("ml_model_outputs/out1")

    models.delete_model_output_edge.assert_called_once_with("ml_model_outputs/out1")
