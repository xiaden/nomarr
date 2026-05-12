# mypy: disable-error-code=func-returns-value
"""Unit tests for ``MlDb`` delegation."""

from __future__ import annotations

from unittest.mock import MagicMock, sentinel

import pytest

from nomarr.persistence.api.ml import MlDb


def _make_ml_db() -> tuple[MlDb, MagicMock, MagicMock, MagicMock]:
    streams = MagicMock()
    vectors = MagicMock()
    models = MagicMock()
    db = MlDb(streams=streams, vectors=vectors, models=models)
    return db, streams, vectors, models


@pytest.mark.unit
def test_register_vector_collection_delegates_to_vectors() -> None:
    db, _, vectors, _ = _make_ml_db()
    vectors.register_vector_collection.return_value = sentinel.result

    result = db.register_vector_collection("vectors_track_hot__model__lib", "vectors_track_hot")

    assert result is sentinel.result
    vectors.register_vector_collection.assert_called_once_with(
        "vectors_track_hot__model__lib",
        "vectors_track_hot",
    )


@pytest.mark.unit
def test_get_output_streams_for_file_delegates_to_streams() -> None:
    db, streams, _, _ = _make_ml_db()
    streams.get_output_streams_for_file.return_value = sentinel.result

    result = db.get_output_streams_for_file("library_files/1")

    assert result is sentinel.result
    streams.get_output_streams_for_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_upsert_output_streams_batch_delegates_to_streams() -> None:
    db, streams, _, _ = _make_ml_db()
    payloads = [{"stream": "mel"}]
    streams.upsert_output_streams_batch.return_value = sentinel.result

    result = db.upsert_output_streams_batch("library_files/1", payloads)

    assert result is sentinel.result
    streams.upsert_output_streams_batch.assert_called_once_with("library_files/1", payloads)


@pytest.mark.unit
def test_delete_output_streams_for_file_delegates_to_streams() -> None:
    db, streams, _, _ = _make_ml_db()
    streams.delete_output_streams_for_file.return_value = sentinel.result

    result = db.delete_output_streams_for_file("library_files/1")

    assert result is sentinel.result
    streams.delete_output_streams_for_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_get_file_vectors_delegates_to_vectors() -> None:
    db, _, vectors, _ = _make_ml_db()
    vectors.get_file_vectors.return_value = sentinel.result

    result = db.get_file_vectors("vectors_track_hot__model__lib", "library_files/1")

    assert result is sentinel.result
    vectors.get_file_vectors.assert_called_once_with("vectors_track_hot__model__lib", "library_files/1")


@pytest.mark.unit
def test_upsert_vector_delegates_to_vectors() -> None:
    db, _, vectors, _ = _make_ml_db()
    payload = {"_key": "vec1"}
    vectors.upsert_vector.return_value = sentinel.result

    result = db.upsert_vector("vectors_track_hot__model__lib", payload)

    assert result is sentinel.result
    vectors.upsert_vector.assert_called_once_with("vectors_track_hot__model__lib", payload)


@pytest.mark.unit
def test_delete_vectors_for_file_delegates_to_vectors() -> None:
    db, _, vectors, _ = _make_ml_db()
    vectors.delete_vectors_for_file.return_value = sentinel.result

    result = db.delete_vectors_for_file("vectors_track_hot__model__lib", "library_files/1")

    assert result is sentinel.result
    vectors.delete_vectors_for_file.assert_called_once_with("vectors_track_hot__model__lib", "library_files/1")


@pytest.mark.unit
def test_vector_search_delegates_to_vectors() -> None:
    db, _, vectors, _ = _make_ml_db()
    query_vector = [0.1, 0.2]
    vectors.vector_search.return_value = sentinel.result

    result = db.vector_search("vectors_track_hot__model__lib", query_vector, limit=5)

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
def test_upsert_model_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    payload = {"_key": "model1"}
    models.upsert_model.return_value = sentinel.result

    result = db.upsert_model(payload)

    assert result is sentinel.result
    models.upsert_model.assert_called_once_with(payload)


@pytest.mark.unit
def test_delete_model_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.delete_model.return_value = sentinel.result

    result = db.delete_model("ml_models/1")

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
def test_get_model_output_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.get_model_output.return_value = sentinel.result

    result = db.get_model_output("ml_model_outputs/1")

    assert result is sentinel.result
    models.get_model_output.assert_called_once_with("ml_model_outputs/1")


@pytest.mark.unit
def test_add_model_output_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    payload = {"name": "energy"}
    models.add_model_output.return_value = sentinel.result

    result = db.add_model_output(payload)

    assert result is sentinel.result
    models.add_model_output.assert_called_once_with(payload)


@pytest.mark.unit
def test_update_model_output_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    fields = {"label": "Energy"}
    models.update_model_output.return_value = sentinel.result

    result = db.update_model_output("ml_model_outputs/1", fields)

    assert result is sentinel.result
    models.update_model_output.assert_called_once_with("ml_model_outputs/1", fields)


@pytest.mark.unit
def test_delete_model_output_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.delete_model_output.return_value = sentinel.result

    result = db.delete_model_output("ml_model_outputs/1")

    assert result is sentinel.result
    models.delete_model_output.assert_called_once_with("ml_model_outputs/1")


@pytest.mark.unit
def test_get_tag_model_output_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.get_tag_model_output.return_value = sentinel.result

    result = db.get_tag_model_output("genre:rock")

    assert result is sentinel.result
    models.get_tag_model_output.assert_called_once_with("genre:rock")


@pytest.mark.unit
def test_upsert_tag_model_output_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    payload = {"key": "genre:rock"}
    models.upsert_tag_model_output.return_value = sentinel.result

    result = db.upsert_tag_model_output(payload)

    assert result is sentinel.result
    models.upsert_tag_model_output.assert_called_once_with(payload)


@pytest.mark.unit
def test_delete_tag_model_outputs_for_model_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.delete_tag_model_outputs_for_model.return_value = sentinel.result

    result = db.delete_tag_model_outputs_for_model("ml_models/1")

    assert result is sentinel.result
    models.delete_tag_model_outputs_for_model.assert_called_once_with("ml_models/1")


@pytest.mark.unit
def test_get_calibration_state_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.get_calibration_state.return_value = sentinel.result

    result = db.get_calibration_state("ml_models/1")

    assert result is sentinel.result
    models.get_calibration_state.assert_called_once_with("ml_models/1")


@pytest.mark.unit
def test_upsert_calibration_state_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    payload = {"state": "ready"}
    models.upsert_calibration_state.return_value = sentinel.result

    result = db.upsert_calibration_state("ml_models/1", payload)

    assert result is sentinel.result
    models.upsert_calibration_state.assert_called_once_with("ml_models/1", payload)


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
def test_delete_calibration_history_for_model_delegates_to_models() -> None:
    db, _, _, models = _make_ml_db()
    models.delete_calibration_history_for_model.return_value = sentinel.result

    result = db.delete_calibration_history_for_model("ml_models/1")

    assert result is sentinel.result
    models.delete_calibration_history_for_model.assert_called_once_with("ml_models/1")
