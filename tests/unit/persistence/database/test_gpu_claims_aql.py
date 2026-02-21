"""Unit tests for GpuClaimOperations (gpu_claims_aql.py)."""

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.database.gpu_claims_aql import GpuClaimOperations


@pytest.fixture
def mock_db():
    """Provide mock ArangoDB."""
    db = MagicMock()
    db.name = "test_db"
    return db


@pytest.fixture
def ops(mock_db):
    """Provide GpuClaimOperations instance."""
    return GpuClaimOperations(mock_db)


class TestAcquireClaim:
    """Test acquire_claim() method."""

    def test_acquire_succeeds_no_existing_claim(self, ops, mock_db):
        """When no claim exists, AQL returns [true] and acquire succeeds."""
        mock_db.aql.execute.return_value = iter([True])

        result = ops.acquire_claim("worker:tag:0")

        assert result is True
        assert mock_db.aql.execute.call_count == 1
        call_args = mock_db.aql.execute.call_args
        bind_vars = call_args[1]["bind_vars"] if "bind_vars" in call_args[1] else call_args[0][1]
        assert bind_vars["worker_id"] == "worker:tag:0"

    def test_acquire_denied_fresh_claim_held(self, ops, mock_db):
        """When another worker holds a fresh claim, AQL returns [] and acquire is denied."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.acquire_claim("worker:tag:1")

        assert result is False

    @patch("nomarr.persistence.database.gpu_claims_aql.now_ms")
    def test_acquire_steals_stale_claim(self, mock_now_ms, ops, mock_db):
        """When existing claim is stale (>60s), AQL returns [true] and acquire succeeds."""
        # Simulate current time = 120_000ms, stale_timeout=60s
        # stale_cutoff = 120_000 - 60_000 = 60_000
        mock_now_ms.return_value = MagicMock(value=120_000)
        mock_db.aql.execute.return_value = iter([True])

        result = ops.acquire_claim("worker:tag:1", stale_timeout_s=60)

        assert result is True
        call_args = mock_db.aql.execute.call_args
        bind_vars = call_args[1]["bind_vars"] if "bind_vars" in call_args[1] else call_args[0][1]
        assert bind_vars["stale_cutoff_ms"] == 60_000
        assert bind_vars["worker_id"] == "worker:tag:1"

    def test_acquire_query_contains_upsert(self, ops, mock_db):
        """Verify the AQL uses UPSERT for atomic check-and-insert."""
        mock_db.aql.execute.return_value = iter([])

        ops.acquire_claim("worker:tag:0")

        query = mock_db.aql.execute.call_args[0][0]
        assert "UPSERT" in query
        assert "singleton" in query
        assert "gpu_warmup_claims" in query


class TestHeartbeatClaim:
    """Test heartbeat_claim() method."""

    def test_heartbeat_succeeds_when_holder(self, ops, mock_db):
        """Heartbeat succeeds when caller is the current holder."""
        mock_db.aql.execute.return_value = iter([True])

        result = ops.heartbeat_claim("worker:tag:0")

        assert result is True
        call_args = mock_db.aql.execute.call_args
        bind_vars = call_args[1]["bind_vars"] if "bind_vars" in call_args[1] else call_args[0][1]
        assert bind_vars["worker_id"] == "worker:tag:0"

    def test_heartbeat_fails_when_not_holder(self, ops, mock_db):
        """Heartbeat fails when another worker holds the claim."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.heartbeat_claim("worker:tag:1")

        assert result is False

    def test_heartbeat_updates_timestamp(self, ops, mock_db):
        """Verify heartbeat AQL updates heartbeat_at field."""
        mock_db.aql.execute.return_value = iter([True])

        ops.heartbeat_claim("worker:tag:0")

        query = mock_db.aql.execute.call_args[0][0]
        assert "heartbeat_at" in query
        assert "UPDATE" in query


class TestReleaseClaim:
    """Test release_claim() method."""

    def test_release_succeeds_when_holder(self, ops, mock_db):
        """Release succeeds when caller is the current holder."""
        mock_db.aql.execute.return_value = iter([True])

        result = ops.release_claim("worker:tag:0")

        assert result is True

    def test_release_noop_when_not_holder(self, ops, mock_db):
        """Release is a no-op when caller does not hold the claim."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.release_claim("worker:tag:1")

        assert result is False

    def test_release_only_removes_own_claim(self, ops, mock_db):
        """Verify AQL filters on worker_id before REMOVE."""
        mock_db.aql.execute.return_value = iter([])

        ops.release_claim("worker:tag:0")

        query = mock_db.aql.execute.call_args[0][0]
        assert "worker_id" in query
        assert "REMOVE" in query
        assert "FILTER" in query


class TestGetClaim:
    """Test get_claim() method."""

    def test_get_claim_returns_document(self, ops, mock_db):
        """Returns claim document when one exists."""
        expected = {"_key": "singleton", "worker_id": "worker:tag:0", "heartbeat_at": 100_000}
        mock_db.collection.return_value.get.return_value = expected

        result = ops.get_claim()

        assert result == expected

    def test_get_claim_returns_none_when_empty(self, ops, mock_db):
        """Returns None when no claim exists."""
        mock_db.collection.return_value.get.return_value = None

        result = ops.get_claim()

        assert result is None

    def test_get_claim_returns_none_on_error(self, ops, mock_db):
        """Returns None if collection access fails."""
        mock_db.collection.return_value.get.side_effect = Exception("collection not found")

        result = ops.get_claim()

        assert result is None
