"""Unit tests for WorkerRestartPolicyOperations (worker_restart_policy_aql.py)."""

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.worker_restart_policy_aql import (
    WorkerRestartPolicyOperations,
)


@pytest.fixture
def mock_db():
    """Provide mock ArangoDB."""
    db = MagicMock()
    db.name = "test_db"
    return db


@pytest.fixture
def ops(mock_db):
    """Provide WorkerRestartPolicyOperations instance."""
    return WorkerRestartPolicyOperations(mock_db)


class TestGetRestartState:
    """Test get_restart_state() method."""

    def test_get_restart_state_no_record(self, ops, mock_db):
        """When no record exists, returns (0, None)."""
        mock_db.aql.execute.return_value = iter([])

        restart_count, last_restart_wall_ms = ops.get_restart_state("worker_0")

        assert restart_count == 0
        assert last_restart_wall_ms is None
        assert mock_db.aql.execute.call_count == 1

    def test_get_restart_state_existing_record(self, ops, mock_db):
        """When record exists, returns (restart_count, last_restart_wall_ms)."""
        mock_db.aql.execute.return_value = iter([{"restart_count": 3, "last_restart_wall_ms": 1234567890}])

        restart_count, last_restart_wall_ms = ops.get_restart_state("worker_1")

        assert restart_count == 3
        assert last_restart_wall_ms == 1234567890


class TestIncrementRestartCount:
    """Test increment_restart_count() method."""

    def test_increment_restart_count_upsert_behavior(self, ops, mock_db):
        """Verify UPSERT query increments or initializes counter."""
        ops.increment_restart_count("worker_2")

        assert mock_db.aql.execute.call_count == 1
        call_args = mock_db.aql.execute.call_args
        query = call_args[0][0]

        # Verify UPSERT, UPDATE, INSERT keywords present
        assert "UPSERT" in query
        assert "UPDATE" in query
        assert "INSERT" in query
        assert "restart_count" in query
        assert "last_restart_wall_ms" in query

        # Verify bind_vars contains component_id
        bind_vars = call_args[1]["bind_vars"]
        assert bind_vars["component_id"] == "worker_2"
        assert "timestamp" in bind_vars  # Uses Milliseconds wrapper, not "now_ms"


class TestResetRestartCount:
    """Test reset_restart_count() method."""

    def test_reset_restart_count_admin_override(self, ops, mock_db):
        """Admin reset sets restart_count=0, preserves component_id."""
        ops.reset_restart_count("worker_3")

        assert mock_db.aql.execute.call_count == 1
        call_args = mock_db.aql.execute.call_args
        query = call_args[0][0]

        # Uses UPDATE not UPSERT (only updates existing records)
        assert "UPDATE" in query
        assert "restart_count: 0" in query

        bind_vars = call_args[1]["bind_vars"]
        assert bind_vars["component_id"] == "worker_3"


class TestMarkFailedPermanent:
    """Test mark_failed_permanent() method."""

    def test_mark_failed_permanent_records_reason(self, ops, mock_db):
        """Marks worker as permanently failed with reason."""
        ops.mark_failed_permanent("worker_4", "Restart limit exceeded")

        assert mock_db.aql.execute.call_count == 1
        call_args = mock_db.aql.execute.call_args
        query = call_args[0][0]

        assert "UPSERT" in query
        assert "UPDATE" in query
        assert "INSERT" in query
        assert "failure_reason" in query
        assert "failed_at_wall_ms" in query  # Uses "_wall_ms" suffix

        bind_vars = call_args[1]["bind_vars"]
        assert bind_vars["component_id"] == "worker_4"
        assert bind_vars["failure_reason"] == "Restart limit exceeded"
        assert "timestamp" in bind_vars  # Uses Milliseconds wrapper
