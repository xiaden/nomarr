"""Focused tests for canonical ``MlModelsAqlOperations`` helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.database.ml_models_aql import MlModelsAqlOperations


@pytest.mark.unit
@pytest.mark.mocked
def test_delete_model_output_edge_removes_edges_by_key_or_output_id() -> None:
    db = MagicMock()
    ops = MlModelsAqlOperations(db)

    ops.delete_model_output_edge("ml_model_outputs/out1")

    db.aql.execute.assert_called_once()
    query = db.aql.execute.call_args.args[0]
    bind_vars = db.aql.execute.call_args.kwargs["bind_vars"]
    assert "edge._key == @edge_key OR edge._to == @output_id" in query
    assert bind_vars == {
        "@collection": ops.MODEL_OUTPUT_EDGE_COLLECTION,
        "edge_key": "out1",
        "output_id": "ml_model_outputs/out1",
    }


@pytest.mark.unit
@pytest.mark.mocked
def test_list_calibration_states_with_models_delegates_to_primitives_execute() -> None:
    db = MagicMock()
    ops = MlModelsAqlOperations(db)
    expected = [{"_key": "state1", "model": {"backbone": "vit"}}]

    with patch("nomarr.persistence.database.ml_models_aql.primitives.execute", return_value=expected) as execute:
        result = ops.list_calibration_states_with_models()

    assert result == expected
    execute.assert_called_once()
    assert execute.call_args.args[0] is db
    query = execute.call_args.args[1]
    bind_vars = execute.call_args.args[2]
    assert "DOCUMENT(edge._from)" in query
    assert bind_vars == {
        "@calibration_collection": ops.CALIBRATION_COLLECTION,
        "@calibration_edge_collection": ops.CALIBRATION_EDGE_COLLECTION,
    }
