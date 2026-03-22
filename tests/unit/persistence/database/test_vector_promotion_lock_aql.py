"""Unit tests for VectorPromotionLockOperations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.database.vector_promotion_lock_aql import (
    VectorPromotionLockOperations,
)


@pytest.fixture
def mock_db() -> MagicMock:
    """Provide mock ArangoDB."""
    db = MagicMock()
    db.name = "test_db"
    return db


@pytest.fixture
def ops(mock_db: MagicMock) -> VectorPromotionLockOperations:
    """Provide VectorPromotionLockOperations instance."""
    return VectorPromotionLockOperations(mock_db)


@pytest.mark.unit
class TestMakeKey:
    """Tests for _make_key static method."""

    def test_make_key_combines_backbone_and_library(self) -> None:
        """Key is backbone__library_key."""
        key = VectorPromotionLockOperations._make_key("effnet", "lib1")
        assert key == "effnet__lib1"

    def test_make_key_preserves_underscores_in_parts(self) -> None:
        """Existing underscores in parts are kept."""
        key = VectorPromotionLockOperations._make_key("my_model", "lib_abc")
        assert key == "my_model__lib_abc"


@pytest.mark.unit
class TestTryAcquireLock:
    """Tests for try_acquire_lock."""

    def test_returns_true_when_insert_succeeds(
        self, ops: VectorPromotionLockOperations, mock_db: MagicMock
    ) -> None:
        """Lock is acquired when INSERT returns a NEW document."""
        mock_db.aql.execute.return_value = iter(
            [{"_key": "effnet__lib1", "locked_by": "w:0", "locked_at": 1000}]
        )

        result = ops.try_acquire_lock("effnet", "lib1", "w:0")

        assert result is True
        assert mock_db.aql.execute.call_count == 1
        call_kwargs = mock_db.aql.execute.call_args
        bind_vars = call_kwargs[1]["bind_vars"] if "bind_vars" in call_kwargs[1] else call_kwargs[0][1]
        assert bind_vars["key"] == "effnet__lib1"
        assert bind_vars["worker_id"] == "w:0"

    def test_returns_false_when_insert_ignored(
        self, ops: VectorPromotionLockOperations, mock_db: MagicMock
    ) -> None:
        """Lock not acquired when document already exists."""
        mock_db.aql.execute.return_value = iter([])

        result = ops.try_acquire_lock("effnet", "lib1", "w:0")

        assert result is False


@pytest.mark.unit
class TestReleaseLock:
    """Tests for release_lock."""

    def test_release_sends_aql_with_locked_by_guard(
        self, ops: VectorPromotionLockOperations, mock_db: MagicMock
    ) -> None:
        """AQL REMOVE uses both _key and locked_by as filters."""
        ops.release_lock("effnet", "lib1", "w:0")

        assert mock_db.aql.execute.call_count == 1
        aql_query = mock_db.aql.execute.call_args[0][0]
        assert "locked_by" in aql_query
        assert "@worker_id" in aql_query

        call_kwargs = mock_db.aql.execute.call_args
        bind_vars = call_kwargs[1]["bind_vars"] if "bind_vars" in call_kwargs[1] else call_kwargs[0][1]
        assert bind_vars["key"] == "effnet__lib1"
        assert bind_vars["worker_id"] == "w:0"


@pytest.mark.unit
class TestForceReleaseLock:
    """Tests for force_release_lock."""

    def test_force_release_omits_locked_by_guard(
        self, ops: VectorPromotionLockOperations, mock_db: MagicMock
    ) -> None:
        """Unconditional remove does not filter by locked_by."""
        ops.force_release_lock("effnet", "lib1")

        assert mock_db.aql.execute.call_count == 1
        call_kwargs = mock_db.aql.execute.call_args
        bind_vars = call_kwargs[1]["bind_vars"] if "bind_vars" in call_kwargs[1] else call_kwargs[0][1]
        assert "worker_id" not in bind_vars
        assert bind_vars["key"] == "effnet__lib1"


@pytest.mark.unit
class TestGetStaleLocks:
    """Tests for get_stale_locks."""

    @patch(
        "nomarr.persistence.database.vector_promotion_lock_aql.now_ms"
    )
    def test_returns_parsed_backbone_library_tuples(
        self,
        mock_now: MagicMock,
        ops: VectorPromotionLockOperations,
        mock_db: MagicMock,
    ) -> None:
        """Stale lock keys are split into (backbone, library) tuples."""
        mock_now.return_value.value = 700_000
        mock_db.aql.execute.return_value = iter(
            ["effnet__lib1", "musicnn__lib2"]
        )

        result = ops.get_stale_locks(stale_after_ms=600_000)

        assert result == [("effnet", "lib1"), ("musicnn", "lib2")]
        call_kwargs = mock_db.aql.execute.call_args
        bind_vars = call_kwargs[1]["bind_vars"] if "bind_vars" in call_kwargs[1] else call_kwargs[0][1]
        assert bind_vars["cutoff"] == 100_000

    @patch(
        "nomarr.persistence.database.vector_promotion_lock_aql.now_ms"
    )
    def test_returns_empty_when_no_stale_locks(
        self,
        mock_now: MagicMock,
        ops: VectorPromotionLockOperations,
        mock_db: MagicMock,
    ) -> None:
        """Empty list when no locks are stale."""
        mock_now.return_value.value = 500_000
        mock_db.aql.execute.return_value = iter([])

        result = ops.get_stale_locks(stale_after_ms=600_000)

        assert result == []
