"""Unit tests for GPU warmup claim component layer.

Verifies the worker_gpu_claim_comp functions correctly wrap the AQL layer
and that the serialization contract holds: when two workers attempt to
acquire simultaneously, only one succeeds.
"""

from unittest.mock import MagicMock

from nomarr.components.workers.worker_gpu_claim_comp import (
    attempt_acquire_gpu_claim,
    heartbeat_gpu_claim,
    release_gpu_claim,
)


def _make_db(acquire_result: bool = True) -> MagicMock:
    """Create a mock Database with configurable gpu_claims behavior."""
    db = MagicMock()
    db.gpu_claims.acquire_claim.return_value = acquire_result
    db.gpu_claims.heartbeat_claim.return_value = True
    db.gpu_claims.release_claim.return_value = True
    return db


class TestAttemptAcquire:
    """Test attempt_acquire_gpu_claim."""

    def test_acquire_succeeds(self) -> None:
        db = _make_db(acquire_result=True)
        assert attempt_acquire_gpu_claim(db, "worker:tag:0") is True
        db.gpu_claims.acquire_claim.assert_called_once_with("worker:tag:0", stale_timeout_s=60)

    def test_acquire_denied(self) -> None:
        db = _make_db(acquire_result=False)
        assert attempt_acquire_gpu_claim(db, "worker:tag:1") is False


class TestTwoWorkerSerialization:
    """Simulate two workers contending for the GPU warmup claim.

    The shared DB mock ensures only the first acquire returns True;
    the second returns False — exactly the serialization contract.
    """

    def test_only_one_worker_acquires_claim(self) -> None:
        db = MagicMock()
        # First call succeeds, second denied
        db.gpu_claims.acquire_claim.side_effect = [True, False]

        w0 = attempt_acquire_gpu_claim(db, "worker:tag:0")
        w1 = attempt_acquire_gpu_claim(db, "worker:tag:1")

        assert w0 is True
        assert w1 is False
        assert db.gpu_claims.acquire_claim.call_count == 2

    def test_denied_worker_can_acquire_after_release(self) -> None:
        db = MagicMock()
        # First call succeeds, second denied, third succeeds (after release)
        db.gpu_claims.acquire_claim.side_effect = [True, False, True]
        db.gpu_claims.release_claim.return_value = True

        w0_acquired = attempt_acquire_gpu_claim(db, "worker:tag:0")
        w1_denied = attempt_acquire_gpu_claim(db, "worker:tag:1")
        assert w0_acquired is True
        assert w1_denied is False

        # Worker 0 releases claim (cache eviction)
        release_gpu_claim(db, "worker:tag:0")
        db.gpu_claims.release_claim.assert_called_once_with("worker:tag:0")

        # Worker 1 retries and succeeds
        w1_retry = attempt_acquire_gpu_claim(db, "worker:tag:1")
        assert w1_retry is True


class TestHeartbeat:
    """Test heartbeat_gpu_claim."""

    def test_heartbeat_succeeds(self) -> None:
        db = _make_db()
        assert heartbeat_gpu_claim(db, "worker:tag:0") is True
        db.gpu_claims.heartbeat_claim.assert_called_once_with("worker:tag:0")

    def test_heartbeat_lost(self) -> None:
        db = _make_db()
        db.gpu_claims.heartbeat_claim.return_value = False
        assert heartbeat_gpu_claim(db, "worker:tag:0") is False


class TestRelease:
    """Test release_gpu_claim."""

    def test_release_succeeds(self) -> None:
        db = _make_db()
        release_gpu_claim(db, "worker:tag:0")
        db.gpu_claims.release_claim.assert_called_once_with("worker:tag:0")

    def test_release_idempotent(self) -> None:
        """Releasing when not holding is a no-op (no exception)."""
        db = _make_db()
        db.gpu_claims.release_claim.return_value = False
        release_gpu_claim(db, "worker:tag:0")  # Should not raise
