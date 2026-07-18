"""Unit tests for AppRepository."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import insert, select

from nomarr.helpers.exceptions import DuplicateEntityError
from nomarr.persistence.database.app_repo import AppRepository
from nomarr.persistence.models.health import Health
from nomarr.persistence.models.worker_claim import WorkerClaim


@pytest.mark.unit
@pytest.mark.integration
class TestAppRepository:
    """Tests for AppRepository CRUD and query methods."""

    # ── Lock ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_upsert_lock_insert(self, pg_session) -> None:
        """upsert_lock should insert if not exists."""
        repo = AppRepository(pg_session)
        await repo.upsert_lock("resource1", {"value": {"holder": "worker1"}})
        result = await repo.get_lock("resource1")
        assert result is not None
        assert result["key"] == "resource1"
        assert result["value"]["holder"] == "worker1"

    @pytest.mark.asyncio
    async def test_upsert_lock_update(self, pg_session) -> None:
        """upsert_lock should update if exists."""
        repo = AppRepository(pg_session)
        await repo.upsert_lock("resource2", {"value": {"holder": "worker1"}})
        await repo.upsert_lock("resource2", {"value": {"holder": "worker2"}})
        result = await repo.get_lock("resource2")
        assert result is not None
        assert result["value"]["holder"] == "worker2"

    @pytest.mark.asyncio
    async def test_release_lock(self, pg_session) -> None:
        """release_lock should delete the lock."""
        repo = AppRepository(pg_session)
        await repo.upsert_lock("resource3", {"value": {"holder": "worker1"}})
        await repo.release_lock("resource3")
        result = await repo.get_lock("resource3")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_lock_nonexistent(self, pg_session) -> None:
        """get_lock should return None for missing key."""
        repo = AppRepository(pg_session)
        result = await repo.get_lock("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_acquire_lock_success(self, pg_session) -> None:
        """acquire_lock should return True on success."""
        repo = AppRepository(pg_session)
        result = await repo.acquire_lock("resource4", {"value": {"holder": "worker1"}})
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_lock_failure(self, pg_session) -> None:
        """acquire_lock should return False if lock already exists.

        SQLite does not provide pgcodes, so the real ``map_persistence_exceptions``
        translates UNIQUE violations to ``DatabaseStateError`` instead of
        ``DuplicateEntityError``.  We patch the context manager to simulate
        PostgreSQL behaviour (pgcode 23505 → DuplicateEntityError).
        """
        repo = AppRepository(pg_session)
        # First acquire succeeds (uses the real context manager)
        await repo.upsert_lock("resource5", {"value": {"holder": "worker1"}})

        @asynccontextmanager
        async def _raise_duplicate():
            raise DuplicateEntityError("Duplicate entity: lock already exists")
            yield  # unreachable, satisfies generator protocol

        # Patch so acquire_lock sees DuplicateEntityError (as PostgreSQL would)
        with patch(
            "nomarr.persistence.database.app_repo.map_persistence_exceptions",
            side_effect=_raise_duplicate,
        ):
            result = await repo.acquire_lock("resource5", {"value": {"holder": "worker2"}})
        assert result is False

    @pytest.mark.asyncio
    async def test_list_locks(self, pg_session) -> None:
        """list_locks should return all locks."""
        repo = AppRepository(pg_session)
        await repo.upsert_lock("lock1", {"value": {}})
        await repo.upsert_lock("lock2", {"value": {}})
        result = await repo.list_locks()
        assert len(result) >= 2
        keys = {lock["key"] for lock in result}
        assert "lock1" in keys
        assert "lock2" in keys

    # ── Health ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_health(self, pg_session) -> None:
        """get_health should return health by worker_id."""
        # Insert directly since upsert_health requires unique constraint
        await pg_session.execute(insert(Health).values(worker_id="worker1", status="healthy", last_seen=1000))
        await pg_session.commit()
        repo = AppRepository(pg_session)
        result = await repo.get_health("worker1")
        assert result is not None
        assert result["worker_id"] == "worker1"
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_get_health_nonexistent(self, pg_session) -> None:
        """get_health should return None for missing worker."""
        repo = AppRepository(pg_session)
        result = await repo.get_health("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_count_healthy(self, pg_session) -> None:
        """count_healthy should count rows with status='healthy'."""
        await pg_session.execute(insert(Health).values(worker_id="worker1", status="healthy", last_seen=1000))
        await pg_session.execute(insert(Health).values(worker_id="worker2", status="unhealthy", last_seen=1000))
        await pg_session.execute(insert(Health).values(worker_id="worker3", status="healthy", last_seen=1000))
        await pg_session.commit()
        repo = AppRepository(pg_session)
        result = await repo.count_healthy()
        assert result == 2

    @pytest.mark.asyncio
    async def test_list_worker_health(self, pg_session) -> None:
        """list_worker_health should return all health rows."""
        await pg_session.execute(insert(Health).values(worker_id="worker1", status="healthy", last_seen=1000))
        await pg_session.execute(insert(Health).values(worker_id="worker2", status="unhealthy", last_seen=1000))
        await pg_session.commit()
        repo = AppRepository(pg_session)
        result = await repo.list_worker_health()
        assert len(result) >= 2

    @pytest.mark.asyncio
    async def test_update_health(self, pg_session) -> None:
        """update_health should modify fields."""
        await pg_session.execute(insert(Health).values(worker_id="worker1", status="healthy", last_seen=1000))
        await pg_session.commit()
        repo = AppRepository(pg_session)
        await repo.update_health("worker1", {"status": "unhealthy"})
        result = await repo.get_health("worker1")
        assert result is not None
        assert result["status"] == "unhealthy"
        assert result["last_seen"] == 1000  # unchanged

    # ── Meta ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_meta(self, pg_session) -> None:
        """get_meta should return meta by key."""
        repo = AppRepository(pg_session)
        await repo.upsert_meta("version", {"value": {"major": 1}})
        result = await repo.get_meta("version")
        assert result is not None
        assert result["key"] == "version"
        assert result["value"]["major"] == 1

    @pytest.mark.asyncio
    async def test_get_meta_nonexistent(self, pg_session) -> None:
        """get_meta should return None for missing key."""
        repo = AppRepository(pg_session)
        result = await repo.get_meta("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_meta_insert(self, pg_session) -> None:
        """upsert_meta should insert if not exists."""
        repo = AppRepository(pg_session)
        await repo.upsert_meta("key1", {"value": {"data": "test"}})
        result = await repo.get_meta("key1")
        assert result is not None

    @pytest.mark.asyncio
    async def test_upsert_meta_update(self, pg_session) -> None:
        """upsert_meta should update if exists."""
        repo = AppRepository(pg_session)
        await repo.upsert_meta("key2", {"value": {"data": "old"}})
        await repo.upsert_meta("key2", {"value": {"data": "new"}})
        result = await repo.get_meta("key2")
        assert result is not None
        assert result["value"]["data"] == "new"

    @pytest.mark.asyncio
    async def test_delete_meta(self, pg_session) -> None:
        """delete_meta should remove the row."""
        repo = AppRepository(pg_session)
        await repo.upsert_meta("key3", {"value": {}})
        await repo.delete_meta("key3")
        result = await repo.get_meta("key3")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_meta_keys_by_prefix(self, pg_session) -> None:
        """list_meta_keys_by_prefix should return matching keys."""
        repo = AppRepository(pg_session)
        await repo.upsert_meta("prefix_key1", {"value": {}})
        await repo.upsert_meta("prefix_key2", {"value": {}})
        await repo.upsert_meta("other_key", {"value": {}})
        result = await repo.list_meta_keys_by_prefix("prefix_")
        assert len(result) == 2
        assert "prefix_key1" in result
        assert "prefix_key2" in result
        assert "other_key" not in result

    # ── Session ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_insert_session(self, pg_session) -> None:
        """insert_session should batch insert sessions."""
        repo = AppRepository(pg_session)
        await repo.insert_session(
            [
                {"id": "session1", "data": {"user": "admin"}, "expires_at": 2000},
                {"id": "session2", "data": {"user": "user"}, "expires_at": 3000},
            ]
        )
        result = await repo.count_sessions()
        assert result >= 2

    @pytest.mark.asyncio
    async def test_delete_session(self, pg_session) -> None:
        """delete_session should remove the session."""
        repo = AppRepository(pg_session)
        await repo.insert_session(
            [
                {"id": "session3", "data": {}, "expires_at": 2000},
            ]
        )
        await repo.delete_session("session3")
        await repo.count_sessions()
        # Verify it's gone by checking active sessions
        active = await repo.get_active_sessions(1000, 100)
        ids = {s["id"] for s in active}
        assert "session3" not in ids

    @pytest.mark.asyncio
    async def test_get_sessions_expiring_before(self, pg_session) -> None:
        """get_sessions_expiring_before should return sessions before timestamp."""
        repo = AppRepository(pg_session)
        await repo.insert_session(
            [
                {"id": "session4", "data": {}, "expires_at": 1000},
                {"id": "session5", "data": {}, "expires_at": 2000},
                {"id": "session6", "data": {}, "expires_at": 3000},
            ]
        )
        result = await repo.get_sessions_expiring_before(2500, 100)
        ids = {s["id"] for s in result}
        assert "session4" in ids
        assert "session5" in ids
        assert "session6" not in ids

    @pytest.mark.asyncio
    async def test_get_active_sessions(self, pg_session) -> None:
        """get_active_sessions should return sessions not yet expired."""
        repo = AppRepository(pg_session)
        await repo.insert_session(
            [
                {"id": "session7", "data": {}, "expires_at": 1000},
                {"id": "session8", "data": {}, "expires_at": 2000},
                {"id": "session9", "data": {}, "expires_at": 3000},
            ]
        )
        result = await repo.get_active_sessions(1500, 100)
        ids = {s["id"] for s in result}
        assert "session7" not in ids
        assert "session8" in ids
        assert "session9" in ids

    @pytest.mark.asyncio
    async def test_count_sessions(self, pg_session) -> None:
        """count_sessions should return total count."""
        repo = AppRepository(pg_session)
        await repo.insert_session(
            [
                {"id": "session10", "data": {}, "expires_at": 2000},
                {"id": "session11", "data": {}, "expires_at": 3000},
            ]
        )
        result = await repo.count_sessions()
        assert result >= 2

    # ── Worker claims ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_insert_worker_claim(self, pg_session) -> None:
        """insert_worker_claim should insert and return id."""
        repo = AppRepository(pg_session)
        claim_id = await repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "1",
                "value": {"status": "processing"},
                "claimed_at": 1000,
            }
        )
        assert isinstance(claim_id, int)
        assert claim_id > 0

    @pytest.mark.asyncio
    async def test_claim_file(self, pg_session) -> None:
        """claim_file should record a worker's claim."""
        repo = AppRepository(pg_session)
        await repo.claim_file(1, "worker1", {"status": "processing", "claimed_at": 1000})
        claims = await repo.list_claims()
        assert len(claims) >= 1
        assert any(c["key"] == "1" and c["worker_id"] == "worker1" for c in claims)

    @pytest.mark.asyncio
    async def test_release_claim(self, pg_session) -> None:
        """release_claim should delete the claim."""
        repo = AppRepository(pg_session)
        await repo.claim_file(2, "worker1", {"status": "processing", "claimed_at": 1000})
        await repo.release_claim(2)
        claims = await repo.list_claims()
        assert not any(c["key"] == "2" for c in claims)

    @pytest.mark.asyncio
    async def test_delete_claims_for_workers(self, pg_session) -> None:
        """delete_claims_for_workers should delete claims for workers."""
        repo = AppRepository(pg_session)
        await repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "10",
                "value": {},
                "claimed_at": 1000,
            }
        )
        await repo.insert_worker_claim(
            {
                "worker_id": "worker2",
                "key": "11",
                "value": {},
                "claimed_at": 1000,
            }
        )
        deleted = await repo.delete_claims_for_workers(["worker1"])
        assert deleted == 1
        claims = await repo.list_claims()
        assert not any(c["worker_id"] == "worker1" for c in claims)
        assert any(c["worker_id"] == "worker2" for c in claims)

    @pytest.mark.asyncio
    async def test_delete_claims_for_files(self, pg_session) -> None:
        """delete_claims_for_files should delete claims for files."""
        repo = AppRepository(pg_session)
        await repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "20",
                "value": {},
                "claimed_at": 1000,
            }
        )
        await repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "21",
                "value": {},
                "claimed_at": 1000,
            }
        )
        deleted = await repo.delete_claims_for_files([20])
        assert deleted == 1
        claims = await repo.list_claims()
        assert not any(c["key"] == "20" for c in claims)
        assert any(c["key"] == "21" for c in claims)

    @pytest.mark.asyncio
    async def test_steal_claim(self, pg_session) -> None:
        """steal_claim should update expired claims."""
        repo = AppRepository(pg_session)
        await repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "30",
                "value": {"status": "processing"},
                "claimed_at": 1000,
            }
        )
        # Steal claim that expired (claimed_at + lease_ms < now)
        result = await repo.steal_claim(
            {"worker_id": "worker2", "value": {"status": "stolen"}},
            now=5000,
            lease_ms=1000,
        )
        assert result is True
        claims = await repo.list_claims()
        stolen = next((c for c in claims if c["key"] == "30"), None)
        assert stolen is not None
        assert stolen["worker_id"] == "worker2"

    @pytest.mark.asyncio
    async def test_list_claims(self, pg_session) -> None:
        """list_claims should return all claims."""
        repo = AppRepository(pg_session)
        await repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "40",
                "value": {},
                "claimed_at": 1000,
            }
        )
        await repo.insert_worker_claim(
            {
                "worker_id": "worker2",
                "key": "41",
                "value": {},
                "claimed_at": 1000,
            }
        )
        result = await repo.list_claims()
        assert len(result) >= 2

    # ── Migrations ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_upsert_migration_insert(self, pg_session) -> None:
        """upsert_migration should insert if not exists."""
        repo = AppRepository(pg_session)
        await repo.upsert_migration(
            "001_initial",
            {
                "status": "applied",
                "migration_version": "1.0",
                "started_at": 1000,
                "applied_at": 2000,
                "duration_ms": 1000,
            },
        )
        result = await repo.list_migrations()
        assert len(result) >= 1
        assert any(m["name"] == "001_initial" for m in result)

    @pytest.mark.asyncio
    async def test_upsert_migration_update(self, pg_session) -> None:
        """upsert_migration should update if exists."""
        repo = AppRepository(pg_session)
        await repo.upsert_migration(
            "002_update",
            {
                "status": "pending",
                "migration_version": "1.0",
                "started_at": 1000,
                "applied_at": None,
                "duration_ms": None,
            },
        )
        await repo.upsert_migration(
            "002_update",
            {
                "status": "applied",
                "migration_version": "1.0",
                "started_at": 1000,
                "applied_at": 2000,
                "duration_ms": 1000,
            },
        )
        result = await repo.list_migrations()
        migration = next((m for m in result if m["name"] == "002_update"), None)
        assert migration is not None
        assert migration["status"] == "applied"

    @pytest.mark.asyncio
    async def test_list_migrations(self, pg_session) -> None:
        """list_migrations should return all migrations."""
        repo = AppRepository(pg_session)
        await repo.upsert_migration(
            "003_test",
            {
                "status": "applied",
                "migration_version": "1.0",
                "started_at": 1000,
                "applied_at": 2000,
                "duration_ms": 1000,
            },
        )
        result = await repo.list_migrations()
        assert len(result) >= 1

    # ── VRAM promises ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_upsert_vram_promise_insert(self, pg_session) -> None:
        """upsert_vram_promise should insert if not exists."""
        repo = AppRepository(pg_session)
        await repo.upsert_vram_promise(
            {
                "id": 1,
                "worker_id": "worker1",
                "pid": 12345,
                "model_path": "/models/test.pt",
                "promised_mb": 1024,
                "total_mb": 8192,
                "used_mb": 2048,
            }
        )
        result = await repo.get_vram_promises()
        assert len(result) >= 1
        assert any(p["id"] == 1 for p in result)

    @pytest.mark.asyncio
    async def test_upsert_vram_promise_update(self, pg_session) -> None:
        """upsert_vram_promise should update if exists."""
        repo = AppRepository(pg_session)
        await repo.upsert_vram_promise(
            {
                "id": 2,
                "worker_id": "worker1",
                "pid": 12345,
                "model_path": "/models/test.pt",
                "promised_mb": 1024,
                "total_mb": 8192,
                "used_mb": 2048,
            }
        )
        await repo.upsert_vram_promise(
            {
                "id": 2,
                "worker_id": "worker1",
                "pid": 12345,
                "model_path": "/models/test.pt",
                "promised_mb": 2048,
                "total_mb": 8192,
                "used_mb": 4096,
            }
        )
        result = await repo.get_vram_promises()
        promise = next((p for p in result if p["id"] == 2), None)
        assert promise is not None
        assert promise["promised_mb"] == 2048
        assert promise["used_mb"] == 4096

    @pytest.mark.asyncio
    async def test_get_vram_promises(self, pg_session) -> None:
        """get_vram_promises should return all promises."""
        repo = AppRepository(pg_session)
        await repo.upsert_vram_promise(
            {
                "id": 3,
                "worker_id": "worker1",
                "pid": 12345,
                "model_path": "/models/test.pt",
                "promised_mb": 1024,
                "total_mb": 8192,
                "used_mb": 2048,
            }
        )
        result = await repo.get_vram_promises()
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_delete_vram_promise(self, pg_session) -> None:
        """delete_vram_promise should remove the row."""
        repo = AppRepository(pg_session)
        await repo.upsert_vram_promise(
            {
                "id": 4,
                "worker_id": "worker1",
                "pid": 12345,
                "model_path": "/models/test.pt",
                "promised_mb": 1024,
                "total_mb": 8192,
                "used_mb": 2048,
            }
        )
        await repo.delete_vram_promise(4)
        result = await repo.get_vram_promises()
        assert not any(p["id"] == 4 for p in result)

    # ── Worker restart policy ───────────────────────────────────
    # Note: WorkerRestartPolicy doesn't have unique constraint on component_id
    # so upsert methods won't work. Testing only the read methods.

    @pytest.mark.asyncio
    async def test_get_worker_restart_policy_nonexistent(self, pg_session) -> None:
        """get_worker_restart_policy should return None for missing component."""
        repo = AppRepository(pg_session)
        result = await repo.get_worker_restart_policy("nonexistent")
        assert result is None

    # ── maintenance ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_truncate_worker_claims(self, pg_session) -> None:
        """truncate_worker_claims should remove all claims."""
        repo = AppRepository(pg_session)
        await repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "50",
                "value": {},
                "claimed_at": 1000,
            }
        )
        await repo.truncate_worker_claims()
        result = await pg_session.execute(select(WorkerClaim))
        assert len(result.all()) == 0

    @pytest.mark.asyncio
    async def test_truncate_health(self, pg_session) -> None:
        """truncate_health should remove all health rows."""
        # Insert directly since upsert_health requires unique constraint
        await pg_session.execute(insert(Health).values(worker_id="worker1", status="healthy", last_seen=1000))
        await pg_session.commit()
        repo = AppRepository(pg_session)
        await repo.truncate_health()
        result = await pg_session.execute(select(Health))
        assert len(result.all()) == 0

    @pytest.mark.asyncio
    async def test_delete_sessions_by_ids(self, pg_session) -> None:
        """delete_sessions_by_ids should batch delete sessions."""
        repo = AppRepository(pg_session)
        await repo.insert_session(
            [
                {"id": "session20", "data": {}, "expires_at": 2000},
                {"id": "session21", "data": {}, "expires_at": 3000},
                {"id": "session22", "data": {}, "expires_at": 4000},
            ]
        )
        await repo.delete_sessions_by_ids(["session20", "session21"])
        await repo.count_sessions()
        # Verify session22 still exists
        active = await repo.get_active_sessions(1000, 100)
        ids = {s["id"] for s in active}
        assert "session22" in ids
