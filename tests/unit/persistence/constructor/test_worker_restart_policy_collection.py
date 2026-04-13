"""Tests for constructor-backed access to the worker_restart_policy collection."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.constructor import SchemaConstructor
from nomarr.persistence.schema import SCHEMA


@pytest.fixture
def mock_db() -> MagicMock:
    """Provide a mock Arango database handle for constructor tests."""
    return MagicMock()


@pytest.fixture
def worker_restart_policy_namespace(mock_db: MagicMock):
    """Provide the constructor-backed worker_restart_policy namespace."""
    return SchemaConstructor(mock_db).build_collection_namespace(
        "worker_restart_policy",
        SCHEMA["worker_restart_policy"],
    )


class TestWorkerRestartPolicyCollection:
    """Migration-coverage tests for the worker_restart_policy constructor namespace."""

    @pytest.mark.unit
    def test_component_lookup_returns_restart_doc(self, worker_restart_policy_namespace, mock_db) -> None:
        """`component_id.get()` replaces the old get_restart_state query input."""
        mock_db.aql.execute.return_value = iter(
            [{"component_id": "worker:tag:0", "restart_count": 2, "last_restart_wall_ms": 12345}],
        )

        assert worker_restart_policy_namespace.component_id.get("worker:tag:0") == {
            "component_id": "worker:tag:0",
            "restart_count": 2,
            "last_restart_wall_ms": 12345,
        }

    @pytest.mark.unit
    def test_component_upsert_accepts_restart_payload(self, worker_restart_policy_namespace, mock_db) -> None:
        """`component_id.upsert()` can persist restart counters by component id."""
        mock_db.aql.execute.return_value = iter(["worker_restart_policy/1"])

        result = worker_restart_policy_namespace.component_id.upsert(
            [{"component_id": "worker:tag:0", "restart_count": 1}],
            match_field="component_id",
        )

        assert result == ["worker_restart_policy/1"]

    @pytest.mark.unit
    def test_component_update_writes_restart_fields(self, worker_restart_policy_namespace, mock_db) -> None:
        """`component_id.update()` replaces the old reset/failure update helpers."""
        worker_restart_policy_namespace.component_id.update(
            "worker:tag:0",
            {"failure_reason": "Restart limit exceeded"},
        )

        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]
        assert bind_vars["field"] == "component_id"
        assert bind_vars["val"] == "worker:tag:0"
