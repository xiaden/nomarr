"""Tests for ``nomarr.components.platform.locks_comp``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.platform.locks_comp import (
    acquire_distributed_lock,
    reap_stale_locks,
    release_distributed_lock,
)


@pytest.mark.unit
class TestAcquireDistributedLock:
    def test_calls_app_add_lock_with_expected_payload(self) -> None:
        db = MagicMock()
        db.app.get_lock.return_value = None

        with patch(
            "nomarr.components.platform.locks_comp.now_ms",
            return_value=SimpleNamespace(value=10_000),
        ):
            result = acquire_distributed_lock(db, "vector_promotion", "file-1", "worker-1", 30)

        assert result is True
        db.app.get_lock.assert_called_once_with("vector_promotion:file-1")
        db.app.add_lock.assert_called_once_with(
            {
                "document_reference": "vector_promotion:file-1",
                "lock_type": "vector_promotion",
                "holder": "worker-1",
                "expires_at": 40_000.0,
                "acquired_at": 10_000.0,
                "status": "active",
            }
        )

    def test_returns_false_when_active_lock_is_held_by_other_owner(self) -> None:
        db = MagicMock()
        db.app.get_lock.return_value = {"expires_at": 10_000.0, "holder": "worker-2"}

        with patch(
            "nomarr.components.platform.locks_comp.now_ms",
            return_value=SimpleNamespace(value=9_000),
        ):
            result = acquire_distributed_lock(db, "vector_promotion", "file-1", "worker-1", 30)

        assert result is False
        db.app.remove_lock.assert_not_called()
        db.app.add_lock.assert_not_called()

    def test_releases_expired_lock_before_reacquiring(self) -> None:
        db = MagicMock()
        db.app.get_lock.return_value = {"expires_at": 5_000.0, "holder": "worker-2"}

        with patch(
            "nomarr.components.platform.locks_comp.now_ms",
            return_value=SimpleNamespace(value=9_000),
        ):
            result = acquire_distributed_lock(db, "vector_promotion", "file-1", "worker-1", 30)

        assert result is True
        db.app.remove_lock.assert_called_once_with("vector_promotion:file-1")
        db.app.add_lock.assert_called_once()


@pytest.mark.unit
class TestReleaseDistributedLock:
    def test_releases_lock_for_matching_owner(self) -> None:
        db = MagicMock()
        db.app.get_lock.side_effect = [
            {"holder": "worker-1"},
            None,
        ]

        result = release_distributed_lock(db, "vector_promotion", "file-1", "worker-1")

        assert result is True
        assert db.app.get_lock.call_args_list == [
            call("vector_promotion:file-1"),
            call("vector_promotion:file-1"),
        ]
        db.app.remove_lock.assert_called_once_with("vector_promotion:file-1")

    def test_returns_false_for_missing_or_foreign_lock(self) -> None:
        db = MagicMock()
        db.app.get_lock.return_value = {"holder": "worker-2"}

        result = release_distributed_lock(db, "vector_promotion", "file-1", "worker-1")

        assert result is False
        db.app.remove_lock.assert_not_called()


@pytest.mark.unit
class TestReapStaleLocks:
    def test_releases_only_stale_vector_promotion_locks(self) -> None:
        db = MagicMock()
        db.app.list_locks.return_value = [
            {
                "document_reference": "vector_promotion:file-1",
                "lock_type": "vector_promotion",
                "acquired_at": 100.0,
            },
            {
                "document_reference": "vector_promotion:file-2",
                "lock_type": "vector_promotion",
                "acquired_at": 9_500.0,
            },
            {
                "document_reference": "other:file-3",
                "lock_type": "other",
                "acquired_at": 100.0,
            },
        ]
        db.app.get_lock.side_effect = [
            {
                "document_reference": "vector_promotion:file-1",
                "lock_type": "vector_promotion",
                "acquired_at": 100.0,
            },
            {
                "document_reference": "vector_promotion:file-2",
                "lock_type": "vector_promotion",
                "acquired_at": 9_500.0,
            },
        ]

        with patch(
            "nomarr.components.platform.locks_comp.now_ms",
            return_value=SimpleNamespace(value=10_000),
        ):
            reap_stale_locks(db, "worker-1", stale_after_ms=1000)

        db.app.list_locks.assert_called_once_with()
        assert db.app.remove_lock.call_args_list == [call("vector_promotion:file-1")]
