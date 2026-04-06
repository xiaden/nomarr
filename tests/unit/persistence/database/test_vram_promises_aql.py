"""Unit tests for VramPromisesOperations (vram_promises_aql.py).

Mock-based — runs without ArangoDB.
"""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.vram_promises_aql import VramPromisesOperations


@pytest.fixture
def ops(mock_db: MagicMock) -> VramPromisesOperations:
    """Provide VramPromisesOperations instance."""
    return VramPromisesOperations(mock_db)


# ==================================================================
# try_register
# ==================================================================


class TestTryRegister:
    """Tests for VramPromisesOperations.try_register."""

    # Helpers — enough headroom: free=3096, sum=100, reserve=256, headroom=2740 > 50
    _ample: ClassVar[dict[str, float]] = {"promised_mb": 50.0, "total_mb": 4096.0, "used_mb": 1000.0}

    @pytest.mark.unit
    def test_returns_true_when_headroom_available(self, ops: VramPromisesOperations, mock_db: MagicMock) -> None:
        """Returns True and issues read + insert when VRAM headroom is sufficient."""
        mock_db.aql.execute.side_effect = [iter([100.0]), MagicMock()]
        result = ops.try_register(worker_id="w1", pid=1, model_path="/m.onnx", **self._ample)
        assert result is True
        assert mock_db.aql.execute.call_count == 2

    @pytest.mark.unit
    def test_returns_false_when_no_headroom(self, ops: VramPromisesOperations, mock_db: MagicMock) -> None:
        """Returns False and skips insert when sum_promised exhausts headroom."""
        # free=3096, sum=3000, reserve=256 => headroom=-160 < 50
        mock_db.aql.execute.return_value = iter([3000.0])
        result = ops.try_register(worker_id="w1", pid=1, model_path="/m.onnx", **self._ample)
        assert result is False
        assert mock_db.aql.execute.call_count == 1

    @pytest.mark.unit
    def test_returns_false_when_headroom_below_reserve(self, ops: VramPromisesOperations, mock_db: MagicMock) -> None:
        """Returns False when free VRAM minus reserve is below promised_mb."""
        # free=496, sum=0, reserve=256 => headroom=240 < 300
        mock_db.aql.execute.return_value = iter([0.0])
        result = ops.try_register(
            worker_id="w1",
            pid=1,
            model_path="/m.onnx",
            promised_mb=300.0,
            total_mb=4096.0,
            used_mb=3600.0,
        )
        assert result is False

    @pytest.mark.unit
    def test_insert_bind_vars_contain_worker_id(self, ops: VramPromisesOperations, mock_db: MagicMock) -> None:
        """Insert bind_vars carry the worker_id argument."""
        mock_db.aql.execute.side_effect = [iter([0.0]), MagicMock()]
        ops.try_register(worker_id="nomarr-tag:0", pid=42, model_path="/m.onnx", **self._ample)
        insert_bind_vars = mock_db.aql.execute.call_args_list[1][1]["bind_vars"]
        assert insert_bind_vars["worker_id"] == "nomarr-tag:0"

    @pytest.mark.unit
    def test_insert_bind_vars_contain_model_path(self, ops: VramPromisesOperations, mock_db: MagicMock) -> None:
        """Insert bind_vars carry the model_path argument."""
        mock_db.aql.execute.side_effect = [iter([0.0]), MagicMock()]
        ops.try_register(worker_id="w1", pid=1, model_path="/models/test.onnx", **self._ample)
        insert_bind_vars = mock_db.aql.execute.call_args_list[1][1]["bind_vars"]
        assert insert_bind_vars["model_path"] == "/models/test.onnx"

    @pytest.mark.unit
    def test_insert_bind_vars_contain_promised_mb(self, ops: VramPromisesOperations, mock_db: MagicMock) -> None:
        """Insert bind_vars carry the promised_mb argument."""
        mock_db.aql.execute.side_effect = [iter([0.0]), MagicMock()]
        ops.try_register(worker_id="w1", pid=1, model_path="/m.onnx", **self._ample)
        insert_bind_vars = mock_db.aql.execute.call_args_list[1][1]["bind_vars"]
        assert insert_bind_vars["promised_mb"] == 50.0

    @pytest.mark.unit
    def test_read_sum_aggregate_has_no_bind_vars(self, ops: VramPromisesOperations, mock_db: MagicMock) -> None:
        """First execute call (SUM aggregate) passes no bind_vars."""
        mock_db.aql.execute.side_effect = [iter([0.0]), MagicMock()]
        ops.try_register(worker_id="w1", pid=1, model_path="/m.onnx", **self._ample)
        first_call = mock_db.aql.execute.call_args_list[0]
        # No keyword bind_vars argument, or it is absent/empty
        bind_vars = first_call[1].get("bind_vars")
        assert bind_vars is None or bind_vars == {}

    @pytest.mark.unit
    def test_returns_true_when_sum_is_none(self, ops: VramPromisesOperations, mock_db: MagicMock) -> None:
        """Treats None sum_promised as 0 — still registers when headroom allows."""
        mock_db.aql.execute.side_effect = [iter([None]), MagicMock()]
        result = ops.try_register(worker_id="w1", pid=1, model_path="/m.onnx", **self._ample)
        assert result is True

    @pytest.mark.unit
    def test_deterministic_key_for_same_worker_model(self, ops: VramPromisesOperations, mock_db: MagicMock) -> None:
        """Same worker_id + model_path always produces the same document key."""
        mock_db.aql.execute.side_effect = [iter([0.0]), MagicMock(), iter([0.0]), MagicMock()]
        ops.try_register(worker_id="w:0", pid=1, model_path="/m.onnx", **self._ample)
        ops.try_register(worker_id="w:0", pid=2, model_path="/m.onnx", **self._ample)
        key1 = mock_db.aql.execute.call_args_list[1][1]["bind_vars"]["key"]
        key2 = mock_db.aql.execute.call_args_list[3][1]["bind_vars"]["key"]
        assert key1 == key2
