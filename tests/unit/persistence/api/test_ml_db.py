# mypy: disable-error-code=func-returns-value
"""Unit tests for ``MlDb`` delegation and contract shape."""

from __future__ import annotations

from unittest.mock import MagicMock, call, sentinel

import pytest

from nomarr.helpers.dataclasses.calibration_state_dataclass import CalibrationState
from nomarr.helpers.dataclasses.ml_embedding_stream_dataclass import EmbeddingStream
from nomarr.helpers.dataclasses.ml_model_dataclass import RegisteredModel
from nomarr.helpers.dataclasses.ml_model_output_dataclass import ModelOutput
from nomarr.helpers.dataclasses.ml_output_stream_dataclass import OutputStream, OutputStreamWrite
from nomarr.persistence.api.ml import MlDb


def _make_ml_db() -> tuple[MlDb, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    vector_repo = MagicMock()
    model_repo = MagicMock()
    output_repo = MagicMock()
    calibration_repo = MagicMock()
    embedding_stream_repo = MagicMock()
    ml_inference_repo = MagicMock()
    db = MlDb(
        session=MagicMock(),
        vector_repo=vector_repo,
        model_repo=model_repo,
        output_repo=output_repo,
        calibration_repo=calibration_repo,
        embedding_stream_repo=embedding_stream_repo,
        ml_inference_repo=ml_inference_repo,
    )
    return db, vector_repo, model_repo, output_repo, calibration_repo, embedding_stream_repo


@pytest.mark.unit
@pytest.mark.parametrize(
    ("repository", "message"),
    (
        ("vector_repo", "VectorRepo is required"),
        ("model_repo", "ModelRepo is required"),
        ("calibration_repo", "CalibrationRepo is required"),
    ),
)
def test_required_repositories_are_validated_without_asserts(repository: str, message: str) -> None:
    repositories: dict[str, object] = {
        "vector_repo": MagicMock(),
        "model_repo": MagicMock(),
        "calibration_repo": MagicMock(),
    }
    repositories[repository] = None

    with pytest.raises(ValueError, match=message):
        MlDb(session=MagicMock(), **repositories)


@pytest.mark.unit
def test_exposes_ml_maintenance_surface() -> None:
    db, vector_repo, _, _, calibration_repo, _ = _make_ml_db()

    assert hasattr(db, "truncate_vectors_in_collection")
    assert hasattr(db, "truncate_calibration_states")
    assert hasattr(db, "truncate_calibration_history")
    assert not hasattr(db, "truncate_vector_collection")
    assert not hasattr(db, "truncate_vector_edges")

    db.truncate_vectors_in_collection("vectors_track_hot__model__lib")
    vector_repo.truncate_embeddings.assert_called_once_with()

    db.truncate_calibration_states()
    calibration_repo.truncate_states.assert_called_once_with()

    db.truncate_calibration_history()
    calibration_repo.truncate_history.assert_called_once_with()


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
def test_list_vector_collection_names_returns_registered_backbones() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.list_models = MagicMock(
        return_value=[
            {
                "id": "musicnn-id",
                "model_type": "head",
                "backbone_id": "musicnn",
                "enabled": 1,
                "created_at": 1,
                "updated_at": 2,
                "path": "musicnn.onnx",
                "backbone": "musicnn",
                "head_type": "classifier",
                "model_stem": "m",
                "output_count": 1,
                "fully_configured": 0,
                "is_known": 0,
                "source": "discovered",
                "head_release_date": "",
                "embedder_release_date": "",
            },
            {
                "id": "effnet-id",
                "model_type": "head",
                "backbone_id": "effnet",
                "enabled": 1,
                "created_at": 1,
                "updated_at": 2,
                "path": "effnet.onnx",
                "backbone": "effnet",
                "head_type": "classifier",
                "model_stem": "e",
                "output_count": 1,
                "fully_configured": 0,
                "is_known": 0,
                "source": "discovered",
                "head_release_date": "",
                "embedder_release_date": "",
            },
            {
                "id": "musicnn-id-2",
                "model_type": "head",
                "backbone_id": "musicnn",
                "enabled": 1,
                "created_at": 1,
                "updated_at": 2,
                "path": "musicnn-2.onnx",
                "backbone": "musicnn",
                "head_type": "classifier",
                "model_stem": "m2",
                "output_count": 1,
                "fully_configured": 0,
                "is_known": 0,
                "source": "discovered",
                "head_release_date": "",
                "embedder_release_date": "",
            },
        ]
    )

    result = db.list_vector_collection_names()

    assert result == ["effnet", "musicnn"]


@pytest.mark.unit
def test_list_vector_namespaces_removed() -> None:
    db, _, _, _, _, _ = _make_ml_db()

    assert not hasattr(db, "list_vector_namespaces")


@pytest.mark.unit
def test_list_output_streams_for_song_maps_repository_rows_to_domain() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.list_output_streams_for_song = MagicMock(
        return_value=[
            {
                "id": 12,
                "song_id": 1,
                "output_id": "out-1",
                "output_index": 2,
                "values": [0.1, 0.2],
                "created_at": 123,
            }
        ]
    )

    result = db.list_output_streams_for_song(1)

    assert result == [OutputStream(output_id="out-1", output_index=2, values=[0.1, 0.2])]
    output_repo.list_output_streams_for_song.assert_called_once_with(1)


@pytest.mark.unit
def test_list_song_vectors_delegates_to_vector_repo() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.get_embeddings_for_song = MagicMock(return_value=sentinel.result)

    result = db.list_song_vectors("vectors_track_hot__model__lib", 1)

    assert result == sentinel.result
    vector_repo.get_embeddings_for_song.assert_called_once_with(1, "vectors_track_hot__model__lib", "cold")


@pytest.mark.unit
def test_search_vectors_delegates_to_vector_repo() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    query_vector = [0.1, 0.2]
    vector_repo.find_nearest = MagicMock(return_value=sentinel.result)

    result = db.search_vectors("openl3", query_vector, limit=5)

    assert result is sentinel.result
    vector_repo.find_nearest.assert_called_once_with(query_vector, backbone_id="openl3", limit=5)


@pytest.mark.unit
def test_get_model_maps_repository_record_to_domain() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.get_model = MagicMock(
        return_value={
            "id": "model1",
            "model_type": "classifier",
            "backbone_id": "effnet",
            "enabled": 1,
            "created_at": 1,
            "updated_at": 2,
            "path": "models/foo.onnx",
            "backbone": "effnet",
            "head_type": "classifier",
            "model_stem": "foo",
            "output_count": 2,
            "fully_configured": 1,
            "is_known": 0,
            "source": "known",
            "head_release_date": "",
            "embedder_release_date": "",
        }
    )

    result = db.get_model("model1")

    assert result == RegisteredModel(
        id="model1",
        path="models/foo.onnx",
        model_type="classifier",
        backbone_id="effnet",
        backbone="effnet",
        head_type="classifier",
        model_stem="foo",
        output_count=2,
        fully_configured=True,
        is_known=False,
        source="known",
        head_release_date="",
        embedder_release_date="",
    )
    model_repo.get_model.assert_called_once_with("model1")


@pytest.mark.unit
def test_get_model_by_path_maps_repository_record_to_domain() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.get_model_by_path = MagicMock(
        return_value={
            "id": "model1",
            "model_type": "classifier",
            "backbone_id": "effnet",
            "enabled": 1,
            "created_at": 1,
            "updated_at": 2,
            "path": "models/foo.onnx",
            "backbone": "effnet",
            "head_type": "classifier",
            "model_stem": "foo",
            "output_count": 2,
            "fully_configured": 0,
            "is_known": 0,
            "source": "known",
        }
    )

    result = db.get_model_by_path("models/foo.onnx")

    assert result is not None
    assert result.id == "model1"
    assert result.path == "models/foo.onnx"
    model_repo.get_model_by_path.assert_called_once_with("models/foo.onnx")


@pytest.mark.unit
def test_get_model_by_type_is_separate_from_path_lookup() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.get_model_by_type = MagicMock(return_value=None)

    assert db.get_model_by_type("classifier") is None
    model_repo.get_model_by_type.assert_called_once_with("classifier")
    model_repo.get_model_by_path.assert_not_called()


@pytest.mark.unit
def test_register_model_maps_complete_required_storage_payload() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.get_model_by_path = MagicMock(return_value=None)
    model_repo.upsert_model = MagicMock(
        return_value={
            "id": "model1",
            "model_type": "sigmoid",
            "backbone_id": "effnet",
            "enabled": 1,
            "created_at": 1,
            "updated_at": 2,
            "path": "models/foo.onnx",
            "backbone": "effnet",
            "head_type": "sigmoid",
            "model_stem": "foo",
            "output_count": 2,
            "fully_configured": 0,
            "is_known": 0,
            "source": "known",
        }
    )

    result = db.register_model(
        path="models/foo.onnx",
        backbone="effnet",
        head_type="sigmoid",
        model_stem="foo",
        output_count=2,
        source="known",
    )

    payload = model_repo.upsert_model.call_args.args[0]
    assert payload["path"] == "models/foo.onnx"
    assert payload["model_type"] == "sigmoid"
    assert payload["backbone_id"] == "effnet"
    assert payload["backbone"] == "effnet"
    assert payload["head_type"] == "sigmoid"
    assert payload["output_count"] == 2
    assert payload["fully_configured"] == 0
    assert payload["is_known"] == 0
    assert result.path == "models/foo.onnx"


@pytest.mark.unit
def test_register_model_preserves_existing_flags_for_idempotent_path_registration() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    existing = {
        "id": "existing-id",
        "model_type": "old-head",
        "backbone_id": "old-backbone",
        "enabled": 1,
        "created_at": 1,
        "updated_at": 2,
        "path": "models/foo.onnx",
        "fully_configured": 1,
        "is_known": 1,
        "registered_at": 42,
    }
    model_repo.get_model_by_path = MagicMock(return_value=existing)
    model_repo.upsert_model = MagicMock(
        return_value={
            **existing,
            "id": "existing-id",
            "model_type": "sigmoid",
            "backbone_id": "effnet",
            "backbone": "effnet",
            "head_type": "sigmoid",
            "model_stem": "foo",
            "output_count": 2,
            "source": "known",
        }
    )

    result = db.register_model(
        path="models/foo.onnx",
        backbone="effnet",
        head_type="sigmoid",
        model_stem="foo",
        output_count=2,
    )

    assert result.path == "models/foo.onnx"
    payload = model_repo.upsert_model.call_args.args[0]
    assert payload["id"] == "existing-id"
    assert payload["fully_configured"] == 1
    assert payload["is_known"] == 1
    assert payload["registered_at"] == 42
    model_repo.get_model_by_path.assert_called_once_with("models/foo.onnx")


@pytest.mark.unit
def test_model_mutation_methods_expose_domain_operations() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.get_model.return_value = {"id": "model1"}

    db.mark_model_fully_configured("model1", True)
    db.mark_model_known("model1", False)

    assert model_repo.update_model.call_args_list == [
        call("model1", {"fully_configured": 1}),
        call("model1", {"is_known": 0}),
    ]


def test_model_mutation_methods_noop_for_missing_model() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.get_model.return_value = None

    db.mark_model_fully_configured("missing", True)
    db.mark_model_known("missing", True)

    model_repo.update_model.assert_not_called()


@pytest.mark.unit
def test_remove_model_delegates_to_model_repo() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.delete_model = MagicMock()

    db.remove_model("model1")

    model_repo.delete_model.assert_called_once_with("model1")


@pytest.mark.unit
def test_list_models_maps_repository_records_to_domain() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.list_models = MagicMock(
        return_value=[
            {
                "id": "model1",
                "model_type": "classifier",
                "backbone_id": "effnet",
                "enabled": 1,
                "created_at": 1,
                "updated_at": 2,
                "path": "models/foo.onnx",
                "backbone": "effnet",
                "head_type": "classifier",
                "model_stem": "foo",
                "output_count": 2,
                "fully_configured": 0,
                "is_known": 1,
                "source": "known",
                "head_release_date": "",
                "embedder_release_date": "",
            }
        ]
    )

    result = db.list_models()

    assert result[0].id == "model1"
    assert result[0].fully_configured is False
    assert result[0].is_known is True
    model_repo.list_models.assert_called_once_with()


@pytest.mark.unit
def test_count_models_delegates_to_model_repo() -> None:
    db, _, model_repo, _, _, _ = _make_ml_db()
    model_repo.count_models = MagicMock(return_value=42)

    result = db.count_models()

    assert result == 42
    model_repo.count_models.assert_called_once_with()


@pytest.mark.unit
def test_get_model_output_delegates_to_output_repo() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.get_output = MagicMock(
        return_value={
            "id": 1,
            "output_id": "output1",
            "model_id": "model1",
            "output_data": {},
            "created_at": 123,
            "output_index": 2,
            "label": "rock",
            "fully_labeled": True,
        }
    )

    result = db.get_model_output("output1")

    assert result == ModelOutput(output_id="output1", output_index=2, label="rock", fully_labeled=True)
    output_repo.get_output.assert_called_once_with("output1")


@pytest.mark.unit
def test_list_model_outputs_delegates_to_output_repo() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.list_model_outputs = MagicMock(
        return_value=[
            {
                "id": 1,
                "output_id": "a",
                "model_id": "model1",
                "output_data": {},
                "created_at": 123,
                "output_index": 0,
                "label": "mood",
                "fully_labeled": True,
            },
            {
                "id": 2,
                "output_id": "b",
                "model_id": "model1",
                "output_data": {},
                "created_at": 124,
                "output_index": 1,
                "label": None,
                "fully_labeled": False,
            },
        ]
    )

    result = db.list_model_outputs("model1")

    assert result == [
        ModelOutput(output_id="a", output_index=0, label="mood", fully_labeled=True),
        ModelOutput(output_id="b", output_index=1, label=None, fully_labeled=False),
    ]
    output_repo.list_model_outputs.assert_called_once_with("model1")


@pytest.mark.unit
def test_get_calibration_state_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.get_state = MagicMock(
        return_value={
            "model_id": "model1",
            "state_data": {"head_name": "genre", "label": "rock", "p5": 0.0, "p95": 1.0},
            "updated_at": 1,
        }
    )

    result = db.get_calibration_state("model1")

    assert result == CalibrationState(model_id="model1", head_name="genre", label="rock", updated_at=1, p5=0.0, p95=1.0)
    calibration_repo.get_state.assert_called_once_with("model1")


@pytest.mark.unit
def test_list_calibration_states_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.list_states = MagicMock(return_value=[])

    result = db.list_calibration_states()

    assert result == []
    calibration_repo.list_states.assert_called_once_with()


@pytest.mark.unit
def test_truncate_vectors_in_collection_delegates_to_vector_repo() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.truncate_embeddings = MagicMock()

    db.truncate_vectors_in_collection("vectors_track_hot__model__lib")

    vector_repo.truncate_embeddings.assert_called_once_with()


@pytest.mark.unit
def test_truncate_calibration_states_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.truncate_states = MagicMock()

    db.truncate_calibration_states()

    calibration_repo.truncate_states.assert_called_once_with()


@pytest.mark.unit
def test_truncate_calibration_history_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.truncate_history = MagicMock()

    db.truncate_calibration_history()

    calibration_repo.truncate_history.assert_called_once_with()


# ---------------------------------------------------------------------------
# Tests for high-risk untested MlDb methods (PostgreSQL rewrite coverage)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_replace_song_inference_results_delegates_to_aggregate_repo() -> None:
    db, _, _, _, _, _ = _make_ml_db()
    vectors = [{"model_id": "model_a", "embedding_vector": [0.1, 0.2]}]
    output_streams = [OutputStreamWrite(output_id="head_0", values=[0.9, 0.1])]

    db.replace_song_inference_results(42, "openl3", vectors=vectors, output_streams=output_streams)

    # The facade is a pure intent forwarder: canonical payloads (output_id/values),
    # backbone scope, and the whole aggregate are delegated in ONE repository call.
    db._ml_inference_repo.replace_song_inference_results.assert_called_once_with(
        song_id=42,
        backbone="openl3",
        vectors=vectors,
        output_streams=[{"output_id": "head_0", "values": [0.9, 0.1], "output_index": None}],
    )


@pytest.mark.unit
def test_replace_song_inference_results_makes_single_aggregate_call() -> None:
    db, vector_repo, _, output_repo, _, _ = _make_ml_db()

    db.replace_song_inference_results(7, "openl3", vectors=[], output_streams=[])

    # The aggregate intent must own the whole replacement: exactly ONE call to the
    # repository aggregate, and NO independent destructive repo calls from the facade.
    db._ml_inference_repo.replace_song_inference_results.assert_called_once()
    vector_repo.delete_embeddings_for_song.assert_not_called()
    output_repo.delete_output_streams_for_song.assert_not_called()


@pytest.mark.unit
def test_independently_destructive_live_write_methods_removed() -> None:
    db, _, _, _, _, _ = _make_ml_db()

    assert not hasattr(db, "replace_output_streams_for_song")
    assert not hasattr(db, "replace_song_vectors")


@pytest.mark.unit
def test_ml_db_exposes_no_facade_transaction_api() -> None:
    db, _, _, _, _, _ = _make_ml_db()

    assert not hasattr(db, "transaction")
    assert not hasattr(db, "_require_transaction")


@pytest.mark.unit
def test_get_calibration_state_view_returns_matching_state() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    state_b = {
        "state_data": {"head_name": "mood", "label": "happy"},
        "id": 2,
        "model_id": "model2",
        "updated_at": 1,
    }
    calibration_repo.get_state_by_head_label = MagicMock(return_value=state_b)

    result = db.get_calibration_state_view("mood", "happy")

    assert result == CalibrationState(model_id="model2", head_name="mood", label="happy", updated_at=1, p5=0.0, p95=1.0)


@pytest.mark.unit
def test_get_calibration_state_view_returns_none_when_no_match() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.get_state_by_head_label = MagicMock(return_value=None)

    result = db.get_calibration_state_view("mood", "happy")

    assert result is None


@pytest.mark.unit
def test_get_calibration_state_view_returns_none_for_empty_list() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.get_state_by_head_label = MagicMock(return_value=None)

    result = db.get_calibration_state_view("genre", "rock")

    assert result is None


@pytest.mark.unit
def test_add_calibration_history_unpacks_payload() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.record_history = MagicMock(return_value=sentinel.history_record)
    payload = {"model_id": "model1", "event": "calibrated", "data": {"accuracy": 0.95}}

    result = db.add_calibration_history(payload)

    assert result is sentinel.history_record
    # record_history(model_id, event, data) has no output_id parameter —
    # calibration history rows carry model_id only, not a fake output key.
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
def test_remove_vectors_for_songs_deletes_each_song_id() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.delete_embeddings_for_song = MagicMock()

    db.remove_vectors_for_songs("openl3", [10, 20, 30])

    assert vector_repo.delete_embeddings_for_song.call_count == 3
    vector_repo.delete_embeddings_for_song.assert_any_call(10, "openl3")
    vector_repo.delete_embeddings_for_song.assert_any_call(20, "openl3")
    vector_repo.delete_embeddings_for_song.assert_any_call(30, "openl3")


@pytest.mark.unit
def test_remove_vectors_for_songs_empty_list_makes_no_calls() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.delete_embeddings_for_song = MagicMock()

    db.remove_vectors_for_songs("openl3", [])

    vector_repo.delete_embeddings_for_song.assert_not_called()


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

    result = db.index_backbone_embeddings("openl3", _embed_dim=128, _nlists=100)

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
def test_replace_embedding_stream_for_song_delegates_to_embedding_stream_repo() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.upsert_stream = MagicMock(return_value={"backbone": "openl3", "patches_emb": b"\x00\x01"})

    result = db.replace_embedding_stream_for_song(42, "openl3", b"\x00\x01")

    assert result == EmbeddingStream(backbone="openl3", patches_emb=b"\x00\x01")
    embedding_stream_repo.upsert_stream.assert_called_once_with(42, "openl3", b"\x00\x01")


@pytest.mark.unit
def test_get_embedding_stream_for_song_delegates_to_embedding_stream_repo() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.get_stream = MagicMock(return_value={"backbone": "openl3", "patches_emb": b"\xab"})

    result = db.get_embedding_stream_for_song(42, "openl3")

    assert result == EmbeddingStream(backbone="openl3", patches_emb=b"\xab")
    embedding_stream_repo.get_stream.assert_called_once_with(42, "openl3")


@pytest.mark.unit
def test_get_embedding_stream_for_song_returns_none_when_absent() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.get_stream = MagicMock(return_value=None)

    result = db.get_embedding_stream_for_song(99, "openl3")

    assert result is None
    embedding_stream_repo.get_stream.assert_called_once_with(99, "openl3")


@pytest.mark.unit
def test_list_embedding_streams_by_backbone_default_params() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.list_by_backbone = MagicMock(return_value=[{"backbone": "openl3", "patches_emb": b"\x01"}])

    result = db.list_embedding_streams_by_backbone("openl3")

    assert result == [EmbeddingStream(backbone="openl3", patches_emb=b"\x01")]
    embedding_stream_repo.list_by_backbone.assert_called_once_with("openl3", limit=50, offset=0)


@pytest.mark.unit
def test_list_embedding_streams_by_backbone_custom_pagination() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.list_by_backbone = MagicMock(
        return_value=[
            {"backbone": "openl3", "patches_emb": b"\x01"},
            {"backbone": "openl3", "patches_emb": b"\x02"},
        ]
    )

    result = db.list_embedding_streams_by_backbone("openl3", limit=10, offset=20)

    assert result == [
        EmbeddingStream(backbone="openl3", patches_emb=b"\x01"),
        EmbeddingStream(backbone="openl3", patches_emb=b"\x02"),
    ]
    embedding_stream_repo.list_by_backbone.assert_called_once_with("openl3", limit=10, offset=20)


@pytest.mark.unit
def test_remove_embedding_streams_for_song_delegates_to_embedding_stream_repo() -> None:
    db, _, _, _, _, embedding_stream_repo = _make_ml_db()
    embedding_stream_repo.delete_for_song = MagicMock()

    db.remove_embedding_streams_for_song(42)

    embedding_stream_repo.delete_for_song.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# Group 2: Output Operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_replace_model_output_delegates_to_output_repo() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.store_model_output = MagicMock(
        return_value={
            "id": 9,
            "output_id": "legacy_key",
            "model_id": "model1",
            "output_data": {},
            "created_at": 123,
            "output_index": 3,
            "label": "rock",
            "fully_labeled": True,
        }
    )

    result = db.replace_model_output(
        "model1",
        "legacy_key",
        output_index=3,
        label="rock",
        fully_labeled=True,
    )

    assert result == ModelOutput(output_id="legacy_key", output_index=3, label="rock", fully_labeled=True)
    output_repo.store_model_output.assert_called_once_with(
        model_id="model1",
        output_id="legacy_key",
        output_data={},
        output_index=3,
        label="rock",
        fully_labeled=True,
    )


@pytest.mark.unit
def test_replace_model_output_defaults_metadata_when_absent() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.store_model_output = MagicMock(
        return_value={
            "id": 10,
            "output_id": "output_1",
            "model_id": "model1",
            "output_data": {},
            "created_at": 123,
            "output_index": None,
            "label": None,
            "fully_labeled": False,
        }
    )

    result = db.replace_model_output("model1", "output_1")

    assert result == ModelOutput(output_id="output_1", output_index=None, label=None, fully_labeled=False)
    output_repo.store_model_output.assert_called_once_with(
        model_id="model1",
        output_id="output_1",
        output_data={},
        output_index=None,
        label=None,
        fully_labeled=False,
    )


@pytest.mark.unit
def test_remove_model_output_delegates_to_output_repo() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.delete_output = MagicMock()

    db.remove_model_output("output_1")

    output_repo.delete_output.assert_called_once_with("output_1")


@pytest.mark.unit
def test_remove_model_outputs_for_model_delegates_to_output_repo() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.delete_outputs_for_model = MagicMock(return_value=["o1", "o2"])

    result = db.remove_model_outputs_for_model("model1")

    assert result == ["o1", "o2"]
    output_repo.delete_outputs_for_model.assert_called_once_with("model1")


@pytest.mark.unit
def test_remove_output_streams_for_song_delegates_to_output_repo() -> None:
    db, _, _, output_repo, _, _ = _make_ml_db()
    output_repo.delete_output_streams_for_song = MagicMock(return_value=3)

    result = db.remove_output_streams_for_song(42)

    assert result == 3
    output_repo.delete_output_streams_for_song.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# Group 3: Calibration State Operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_all_calibration_states_with_models_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.list_states_with_models = MagicMock(return_value=[])

    result = db.list_all_calibration_states_with_models()

    assert result == []
    calibration_repo.list_states_with_models.assert_called_once_with()


@pytest.mark.unit
def test_replace_calibration_state_delegates_to_calibration_repo_ignoring_key() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.set_state = MagicMock(
        return_value={
            "model_id": "model1",
            "state_data": {"head_name": "genre", "label": "rock"},
            "updated_at": 1,
        }
    )
    state = CalibrationState(model_id="model1", head_name="genre", label="rock")

    result = db.replace_calibration_state(state)

    assert result == CalibrationState(model_id="model1", head_name="genre", label="rock", updated_at=1, p5=0.0, p95=1.0)
    calibration_repo.set_state.assert_called_once_with(
        "model1",
        state_data={
            "head_name": "genre",
            "label": "rock",
            "calibration_def_hash": "",
            "histogram": {},
            "histogram_bins": None,
            "p5": None,
            "p95": None,
            "n": 0,
            "underflow_count": 0,
            "overflow_count": 0,
        },
    )


@pytest.mark.unit
def test_remove_calibration_state_delegates_to_calibration_repo() -> None:
    db, _, _, _, calibration_repo, _ = _make_ml_db()
    calibration_repo.delete_state = MagicMock()
    state = CalibrationState(model_id="model1", head_name="genre", label="rock")

    db.remove_calibration_state(state)

    calibration_repo.delete_state.assert_called_once_with("model1", "genre", "rock")


# ---------------------------------------------------------------------------
# Group 4: Vector Operations
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_remove_song_vectors_delegates_backbone_scope_to_vector_repo() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.delete_embeddings_for_song = MagicMock()

    db.remove_song_vectors("vectors_track_hot__model__lib", 42)

    vector_repo.delete_embeddings_for_song.assert_called_once_with(42, "vectors_track_hot__model__lib")


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
    db.rebuild_backbone_embedding_index("openl3")


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


@pytest.mark.unit
def test_get_embedding_stats_delegates_library_scope_to_vector_repo() -> None:
    db, vector_repo, _, _, _, _ = _make_ml_db()
    vector_repo.get_embedding_stats = MagicMock(return_value=sentinel.result)

    result = db.get_embedding_stats("openl3", library_id=7)

    assert result is sentinel.result
    vector_repo.get_embedding_stats.assert_called_once_with("openl3", library_id=7)
