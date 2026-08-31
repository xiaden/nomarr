"""Unit tests for AppRepository."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import insert, select

from nomarr.helpers.exceptions import DuplicateEntityError
from nomarr.persistence.database.app_repo import AppRepository
from nomarr.persistence.models.health import Health
from nomarr.persistence.models.worker_claim import WorkerClaim
from nomarr.persistence.models.worker_restart_policy import WorkerRestartPolicy


@pytest.mark.unit
@pytest.mark.integration
class TestAppRepository:
    """Tests for AppRepository CRUD and query methods."""

    # ── Lock ────────────────────────────────────────────────────

    def test_upsert_lock_insert(self, pg_session) -> None:
        """upsert_lock should insert if not exists."""
        repo = AppRepository(pg_session)
        repo.upsert_lock("resource1", {"value": {"holder": "worker1"}})
        result = repo.get_lock("resource1")
        assert result is not None
        assert result["key"] == "resource1"
        assert result["value"]["holder"] == "worker1"

    def test_upsert_lock_update(self, pg_session) -> None:
        """upsert_lock should update if exists."""
        repo = AppRepository(pg_session)
        repo.upsert_lock("resource2", {"value": {"holder": "worker1"}})
        repo.upsert_lock("resource2", {"value": {"holder": "worker2"}})
        result = repo.get_lock("resource2")
        assert result is not None
        assert result["value"]["holder"] == "worker2"

    def test_release_lock(self, pg_session) -> None:
        """release_lock should delete the lock."""
        repo = AppRepository(pg_session)
        repo.upsert_lock("resource3", {"value": {"holder": "worker1"}})
        repo.release_lock("resource3")
        result = repo.get_lock("resource3")
        assert result is None

    def test_get_lock_nonexistent(self, pg_session) -> None:
        """get_lock should return None for missing key."""
        repo = AppRepository(pg_session)
        result = repo.get_lock("nonexistent")
        assert result is None

    def test_acquire_lock_success(self, pg_session) -> None:
        """acquire_lock should return True on success."""
        repo = AppRepository(pg_session)
        result = repo.acquire_lock("resource4", {"value": {"holder": "worker1"}})
        assert result is True

    def test_acquire_lock_failure(self, pg_session) -> None:
        """acquire_lock should return False if lock already exists.

        SQLite does not provide pgcodes, so the real ``map_persistence_exceptions``
        translates UNIQUE violations to ``DatabaseStateError`` instead of
        ``DuplicateEntityError``.  We patch the context manager to simulate
        PostgreSQL behaviour (pgcode 23505 → DuplicateEntityError).
        """
        repo = AppRepository(pg_session)
        # First acquire succeeds (uses the real context manager)
        repo.upsert_lock("resource5", {"value": {"holder": "worker1"}})

        @contextmanager
        def _raise_duplicate():
            raise DuplicateEntityError("Duplicate entity: lock already exists")
            yield  # unreachable, satisfies generator protocol

        # Patch so acquire_lock sees DuplicateEntityError (as PostgreSQL would)
        with patch(
            "nomarr.persistence.database.app_repo.map_persistence_exceptions",
            side_effect=_raise_duplicate,
        ):
            result = repo.acquire_lock("resource5", {"value": {"holder": "worker2"}})
        assert result is False

    def test_list_locks(self, pg_session) -> None:
        """list_locks should return all locks."""
        repo = AppRepository(pg_session)
        repo.upsert_lock("lock1", {"value": {}})
        repo.upsert_lock("lock2", {"value": {}})
        result = repo.list_locks()
        assert len(result) >= 2
        keys = {lock["key"] for lock in result}
        assert "lock1" in keys
        assert "lock2" in keys

    # ── Health ──────────────────────────────────────────────────

    def test_get_health(self, pg_session) -> None:
        """get_health should return health by worker_id."""
        # Insert directly since upsert_health requires unique constraint
        pg_session.execute(insert(Health).values(worker_id="worker1", status="healthy", last_seen=1000))
        pg_session.commit()
        repo = AppRepository(pg_session)
        result = repo.get_health("worker1")
        assert result is not None
        assert result["worker_id"] == "worker1"
        assert result["status"] == "healthy"

    def test_get_health_nonexistent(self, pg_session) -> None:
        """get_health should return None for missing worker."""
        repo = AppRepository(pg_session)
        result = repo.get_health("nonexistent")
        assert result is None

    def test_count_healthy(self, pg_session) -> None:
        """count_healthy should count rows with status='healthy'."""
        pg_session.execute(insert(Health).values(worker_id="worker1", status="healthy", last_seen=1000))
        pg_session.execute(insert(Health).values(worker_id="worker2", status="unhealthy", last_seen=1000))
        pg_session.execute(insert(Health).values(worker_id="worker3", status="healthy", last_seen=1000))
        pg_session.commit()
        repo = AppRepository(pg_session)
        result = repo.count_healthy()
        assert result == 2

    def test_list_worker_health(self, pg_session) -> None:
        """list_worker_health should return all health rows."""
        pg_session.execute(insert(Health).values(worker_id="worker1", status="healthy", last_seen=1000))
        pg_session.execute(insert(Health).values(worker_id="worker2", status="unhealthy", last_seen=1000))
        pg_session.commit()
        repo = AppRepository(pg_session)
        result = repo.list_worker_health()
        assert len(result) >= 2

    def test_update_health(self, pg_session) -> None:
        """update_health should modify fields."""
        pg_session.execute(insert(Health).values(worker_id="worker1", status="healthy", last_seen=1000))
        pg_session.commit()
        repo = AppRepository(pg_session)
        repo.update_health("worker1", {"status": "unhealthy"})
        result = repo.get_health("worker1")
        assert result is not None
        assert result["status"] == "unhealthy"
        assert result["last_seen"] == 1000  # unchanged

    def test_update_health_creates_row_and_ignores_unknown_fields(self, pg_session) -> None:
        """Runtime health writes create rows and ignore unknown fields."""
        repo = AppRepository(pg_session)

        repo.update_health(
            "worker1",
            {
                "status": "healthy",
                "last_seen": 2000,
                "component_type": "worker",
            },
        )

        result = repo.get_health("worker1")
        assert result is not None
        assert result["worker_id"] == "worker1"
        assert result["status"] == "healthy"
        assert result["last_seen"] == 2000

    def test_upsert_health_creates_and_updates_row_without_unique_constraint(self, pg_session) -> None:
        """upsert_health should work when worker_id has no unique constraint."""
        repo = AppRepository(pg_session)

        repo.upsert_health("worker1", {"status": "healthy", "last_seen": 1000})
        repo.upsert_health("worker1", {"status": "unhealthy", "last_seen": 2000})

        result = repo.get_health("worker1")
        assert result is not None
        assert result["status"] == "unhealthy"
        assert result["last_seen"] == 2000

    # ── Meta ────────────────────────────────────────────────────

    def test_get_meta(self, pg_session) -> None:
        """get_meta should return meta by key."""
        repo = AppRepository(pg_session)
        repo.upsert_meta("version", {"value": {"major": 1}})
        result = repo.get_meta("version")
        assert result is not None
        assert result["key"] == "version"
        assert result["value"]["major"] == 1

    def test_get_meta_nonexistent(self, pg_session) -> None:
        """get_meta should return None for missing key."""
        repo = AppRepository(pg_session)
        result = repo.get_meta("nonexistent")
        assert result is None

    def test_upsert_meta_insert(self, pg_session) -> None:
        """upsert_meta should insert if not exists."""
        repo = AppRepository(pg_session)
        repo.upsert_meta("key1", {"value": {"data": "test"}})
        result = repo.get_meta("key1")
        assert result is not None

    def test_upsert_meta_update(self, pg_session) -> None:
        """upsert_meta should update if exists."""
        repo = AppRepository(pg_session)
        repo.upsert_meta("key2", {"value": {"data": "old"}})
        repo.upsert_meta("key2", {"value": {"data": "new"}})
        result = repo.get_meta("key2")
        assert result is not None
        assert result["value"]["data"] == "new"

    def test_delete_meta(self, pg_session) -> None:
        """delete_meta should remove the row."""
        repo = AppRepository(pg_session)
        repo.upsert_meta("key3", {"value": {}})
        repo.delete_meta("key3")
        result = repo.get_meta("key3")
        assert result is None

    def test_list_meta_keys_by_prefix(self, pg_session) -> None:
        """list_meta_keys_by_prefix should return matching keys."""
        repo = AppRepository(pg_session)
        repo.upsert_meta("prefix_key1", {"value": {}})
        repo.upsert_meta("prefix_key2", {"value": {}})
        repo.upsert_meta("other_key", {"value": {}})
        result = repo.list_meta_keys_by_prefix("prefix_")
        assert len(result) == 2
        assert "prefix_key1" in result
        assert "prefix_key2" in result
        assert "other_key" not in result

    # ── Session ─────────────────────────────────────────────────

    def test_insert_session(self, pg_session) -> None:
        """insert_session should batch insert sessions."""
        repo = AppRepository(pg_session)
        repo.insert_session(
            [
                {"id": "session1", "data": {"user": "admin"}, "expires_at": 2000},
                {"id": "session2", "data": {"user": "user"}, "expires_at": 3000},
            ]
        )
        result = repo.count_sessions()
        assert result >= 2

    def test_delete_session(self, pg_session) -> None:
        """delete_session should remove the session."""
        repo = AppRepository(pg_session)
        repo.insert_session(
            [
                {"id": "session3", "data": {}, "expires_at": 2000},
            ]
        )
        repo.delete_session("session3")
        repo.count_sessions()
        # Verify it's gone by checking active sessions
        active = repo.get_active_sessions(1000, 100)
        ids = {s["id"] for s in active}
        assert "session3" not in ids

    def test_get_sessions_expiring_before(self, pg_session) -> None:
        """get_sessions_expiring_before should return sessions before timestamp."""
        repo = AppRepository(pg_session)
        repo.insert_session(
            [
                {"id": "session4", "data": {}, "expires_at": 1000},
                {"id": "session5", "data": {}, "expires_at": 2000},
                {"id": "session6", "data": {}, "expires_at": 3000},
            ]
        )
        result = repo.get_sessions_expiring_before(2500, 100)
        ids = {s["id"] for s in result}
        assert "session4" in ids
        assert "session5" in ids
        assert "session6" not in ids

    def test_get_active_sessions(self, pg_session) -> None:
        """get_active_sessions should return sessions not yet expired."""
        repo = AppRepository(pg_session)
        repo.insert_session(
            [
                {"id": "session7", "data": {}, "expires_at": 1000},
                {"id": "session8", "data": {}, "expires_at": 2000},
                {"id": "session9", "data": {}, "expires_at": 3000},
            ]
        )
        result = repo.get_active_sessions(1500, 100)
        ids = {s["id"] for s in result}
        assert "session7" not in ids
        assert "session8" in ids
        assert "session9" in ids

    def test_count_sessions(self, pg_session) -> None:
        """count_sessions should return total count."""
        repo = AppRepository(pg_session)
        repo.insert_session(
            [
                {"id": "session10", "data": {}, "expires_at": 2000},
                {"id": "session11", "data": {}, "expires_at": 3000},
            ]
        )
        result = repo.count_sessions()
        assert result >= 2

    # ── Worker claims ───────────────────────────────────────────

    def test_insert_worker_claim(self, pg_session) -> None:
        """insert_worker_claim should insert and return id."""
        repo = AppRepository(pg_session)
        claim_id = repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "1",
                "value": {"status": "processing"},
                "claimed_at": 1000,
            }
        )
        assert isinstance(claim_id, int)
        assert claim_id > 0

    def test_insert_worker_claim_rejects_missing_song(self, pg_session) -> None:
        repo = AppRepository(pg_session)
        from unittest.mock import MagicMock

        repo._song_repo = MagicMock()
        repo._song_repo.get_song.return_value = None

        with pytest.raises(ValueError, match="Song 999 does not exist"):
            repo.insert_worker_claim({"worker_id": "w1", "key": "k", "file_id": 999})

    def test_claim_file(self, pg_session) -> None:
        """claim_file should record a worker's claim."""
        repo = AppRepository(pg_session)
        repo.claim_file(1, "worker1", {"status": "processing", "claimed_at": 1000})
        claims = repo.list_claims()
        assert len(claims) >= 1
        assert any(c["key"] == "claim_1" and c["worker_id"] == "worker1" for c in claims)

    def test_release_claim(self, pg_session) -> None:
        """release_claim should delete the claim."""
        repo = AppRepository(pg_session)
        repo.claim_file(2, "worker1", {"status": "processing", "claimed_at": 1000})
        repo.release_claim(2)
        claims = repo.list_claims()
        assert not any(c["key"] == "claim_2" for c in claims)

    def test_release_claim_by_song_ignores_owner(self, pg_session) -> None:
        """Expired claim stealing should remove a claim owned by another worker."""
        repo = AppRepository(pg_session)
        repo.claim_file(3, "worker1", {"status": "processing", "claimed_at": 1000})
        repo.release_claim_by_song(3)
        claims = repo.list_claims()
        assert not any(c["key"] == "claim_3" for c in claims)

    def test_release_claim_removes_untyped_claim(self, pg_session) -> None:
        """The default release path removes claims created without a type."""
        repo = AppRepository(pg_session)
        repo.claim_file(4, "worker1", {"status": "processing", "claimed_at": 1000})
        repo.release_claim("worker1", 4)
        claims = repo.list_claims()
        assert not any(c["key"] == "claim_4" for c in claims)

    def test_delete_claims_for_workers(self, pg_session) -> None:
        """delete_claims_for_workers should delete claims for workers."""
        repo = AppRepository(pg_session)
        repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "10",
                "value": {},
                "claimed_at": 1000,
            }
        )
        repo.insert_worker_claim(
            {
                "worker_id": "worker2",
                "key": "11",
                "value": {},
                "claimed_at": 1000,
            }
        )
        deleted = repo.delete_claims_for_workers(["worker1"])
        assert deleted == 1
        claims = repo.list_claims()
        assert not any(c["worker_id"] == "worker1" for c in claims)
        assert any(c["worker_id"] == "worker2" for c in claims)

    def test_delete_claims_for_songs(self, pg_session) -> None:
        """delete_claims_for_songs should delete claims for songs."""
        repo = AppRepository(pg_session)
        repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "claim_20",
                "value": {},
                "claimed_at": 1000,
            }
        )
        repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "claim_custom_type_20",
                "value": {},
                "claimed_at": 1000,
            }
        )
        repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "claim_21",
                "value": {},
                "claimed_at": 1000,
            }
        )
        deleted = repo.delete_claims_for_songs([20])
        assert deleted == 2
        claims = repo.list_claims()
        assert not any(c["key"] == "claim_20" for c in claims)
        assert not any(c["key"] == "claim_custom_type_20" for c in claims)
        assert any(c["key"] == "claim_21" for c in claims)

    def test_delete_claims_deduplicates_overlapping_worker_and_song_filters(self, pg_session) -> None:
        """Overlapping filters delete each matching claim once in one transaction."""
        repo = AppRepository(pg_session)
        repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "claim_20",
                "value": {},
                "claimed_at": 1000,
            }
        )
        repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "claim_21",
                "value": {},
                "claimed_at": 1000,
            }
        )

        deleted = repo.delete_claims(worker_ids=["worker1"], song_ids=[20])

        assert deleted == 2
        assert repo.list_claims() == []

    def test_steal_claim(self, pg_session) -> None:
        """steal_claim should update expired claims."""
        repo = AppRepository(pg_session)
        repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "30",
                "value": {"status": "processing"},
                "claimed_at": 1000,
            }
        )
        # Steal claim that expired (claimed_at + lease_ms < now)
        result = repo.steal_claim(
            {
                "key": "30",
                "worker_id": "worker2",
                "value": {"status": "stolen"},
                "claimed_at": 5000,
            },
            now=5000,
            lease_ms=1000,
        )
        assert result is True
        claims = repo.list_claims()
        stolen = next((c for c in claims if c["key"] == "30"), None)
        assert stolen is not None
        assert stolen["worker_id"] == "worker2"

    def test_steal_claim_only_updates_targeted_expired_claim(self, pg_session) -> None:
        """A steal cannot update a different claim or an active claim."""
        repo = AppRepository(pg_session)
        repo.insert_worker_claim({"worker_id": "worker1", "key": "claim_31", "value": {}, "claimed_at": 1000})
        repo.insert_worker_claim({"worker_id": "worker1", "key": "claim_32", "value": {}, "claimed_at": 4900})

        result = repo.steal_claim(
            {
                "key": "claim_32",
                "worker_id": "worker2",
                "value": {},
                "claimed_at": 5000,
            },
            now=5000,
            lease_ms=1000,
        )

        assert result is False
        claims = {claim["key"]: claim for claim in repo.list_claims()}
        assert claims["claim_31"]["worker_id"] == "worker1"
        assert claims["claim_32"]["worker_id"] == "worker1"

    def test_list_claims(self, pg_session) -> None:
        """list_claims should return all claims."""
        repo = AppRepository(pg_session)
        repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "40",
                "value": {},
                "claimed_at": 1000,
            }
        )
        repo.insert_worker_claim(
            {
                "worker_id": "worker2",
                "key": "41",
                "value": {},
                "claimed_at": 1000,
            }
        )
        result = repo.list_claims()
        assert len(result) >= 2

    # ── Migrations ──────────────────────────────────────────────

    def test_upsert_migration_insert(self, pg_session) -> None:
        """upsert_migration should insert if not exists."""
        repo = AppRepository(pg_session)
        repo.upsert_migration(
            "001_initial",
            {
                "status": "applied",
                "migration_version": "1.0",
                "started_at": 1000,
                "applied_at": 2000,
                "duration_ms": 1000,
            },
        )
        result = repo.list_migrations()
        assert len(result) >= 1
        assert any(m["name"] == "001_initial" for m in result)

    def test_upsert_migration_update(self, pg_session) -> None:
        """upsert_migration should update if exists."""
        repo = AppRepository(pg_session)
        repo.upsert_migration(
            "002_update",
            {
                "status": "pending",
                "migration_version": "1.0",
                "started_at": 1000,
                "applied_at": None,
                "duration_ms": None,
            },
        )
        repo.upsert_migration(
            "002_update",
            {
                "status": "applied",
                "migration_version": "1.0",
                "started_at": 1000,
                "applied_at": 2000,
                "duration_ms": 1000,
            },
        )
        result = repo.list_migrations()
        migration = next((m for m in result if m["name"] == "002_update"), None)
        assert migration is not None
        assert migration["status"] == "applied"

    def test_list_migrations(self, pg_session) -> None:
        """list_migrations should return all migrations."""
        repo = AppRepository(pg_session)
        repo.upsert_migration(
            "003_test",
            {
                "status": "applied",
                "migration_version": "1.0",
                "started_at": 1000,
                "applied_at": 2000,
                "duration_ms": 1000,
            },
        )
        result = repo.list_migrations()
        assert len(result) >= 1

    # ── VRAM promises ───────────────────────────────────────────

    def test_insert_vram_promise(self, pg_session) -> None:
        repo = AppRepository(pg_session)
        repo.insert_vram_promise(
            worker_id="worker1",
            pid=12345,
            model_path="/models/test.pt",
            promised_mb=1024,
            total_mb=8192,
            used_mb=2048,
        )

        result = repo.get_vram_promises()
        assert any(p.worker_id == "worker1" and p.model_path == "/models/test.pt" for p in result)

    def test_get_vram_promises(self, pg_session) -> None:
        repo = AppRepository(pg_session)
        repo.insert_vram_promise(
            worker_id="worker1",
            pid=12345,
            model_path="/models/test.pt",
            promised_mb=1024,
            total_mb=8192,
            used_mb=2048,
        )

        result = repo.get_vram_promises()
        assert len(result) >= 1
        assert all(not hasattr(p, "id") for p in result)

    def test_count_vram_promises(self, pg_session) -> None:
        repo = AppRepository(pg_session)
        assert repo.count_vram_promises() >= 0

    def test_delete_vram_promise_by_worker_model(self, pg_session) -> None:
        repo = AppRepository(pg_session)
        for worker_id, model_path in (
            ("worker1", "/models/test.pt"),
            ("worker1", "/models/test.pt"),
            ("worker2", "/models/test.pt"),
        ):
            repo.insert_vram_promise(
                worker_id=worker_id,
                pid=12345,
                model_path=model_path,
                promised_mb=1024,
                total_mb=8192,
                used_mb=2048,
            )

        deleted = repo.delete_vram_promise_by_worker_model("worker1", "/models/test.pt")

        assert deleted == 2
        result = repo.get_vram_promises()
        assert not any(p.worker_id == "worker1" for p in result)
        assert any(p.worker_id == "worker2" for p in result)

    def test_delete_vram_promises_by_worker(self, pg_session) -> None:
        repo = AppRepository(pg_session)
        for worker_id in ("worker1", "worker1", "worker2"):
            repo.insert_vram_promise(
                worker_id=worker_id,
                pid=12345,
                model_path="/models/test.pt",
                promised_mb=1024,
                total_mb=8192,
                used_mb=2048,
            )

        deleted = repo.delete_vram_promises_by_worker("worker1")

        assert deleted == 2
        result = repo.get_vram_promises()
        assert not any(p.worker_id == "worker1" for p in result)
        assert any(p.worker_id == "worker2" for p in result)

    # ── Worker restart policy ───────────────────────────────────

    def test_get_worker_restart_policy_nonexistent(self, pg_session) -> None:
        """get_worker_restart_policy should return None for missing component."""
        repo = AppRepository(pg_session)
        result = repo.get_worker_restart_policy("nonexistent")
        assert result is None

    def test_upsert_worker_restart_policy_insert_and_update(self, pg_session) -> None:
        """Restart policy writes insert once and update the same component row."""
        repo = AppRepository(pg_session)

        repo.upsert_worker_restart_policy("worker-1", {"restart_count": 1})
        repo.upsert_worker_restart_policy("worker-1", {"restart_count": 2, "failed": True})

        result = repo.get_worker_restart_policy("worker-1")
        assert result == {"restart_count": 2, "failed": True}
        rows = pg_session.execute(
            select(WorkerRestartPolicy).where(WorkerRestartPolicy.component_id == "worker-1")
        ).all()
        assert len(rows) == 1

    # ── maintenance ─────────────────────────────────────────────

    def test_truncate_worker_claims(self, pg_session) -> None:
        """truncate_worker_claims should remove all claims."""
        repo = AppRepository(pg_session)
        repo.insert_worker_claim(
            {
                "worker_id": "worker1",
                "key": "50",
                "value": {},
                "claimed_at": 1000,
            }
        )
        repo.truncate_worker_claims()
        result = pg_session.execute(select(WorkerClaim))
        assert len(result.all()) == 0

    def test_truncate_health(self, pg_session) -> None:
        """truncate_health should remove all health rows."""
        # Insert directly since upsert_health requires unique constraint
        pg_session.execute(insert(Health).values(worker_id="worker1", status="healthy", last_seen=1000))
        pg_session.commit()
        repo = AppRepository(pg_session)
        repo.truncate_health()
        result = pg_session.execute(select(Health))
        assert len(result.all()) == 0

    def test_delete_sessions_by_ids(self, pg_session) -> None:
        """delete_sessions_by_ids should batch delete sessions."""
        repo = AppRepository(pg_session)
        repo.insert_session(
            [
                {"id": "session20", "data": {}, "expires_at": 2000},
                {"id": "session21", "data": {}, "expires_at": 3000},
                {"id": "session22", "data": {}, "expires_at": 4000},
            ]
        )
        repo.delete_sessions_by_ids(["session20", "session21"])
        repo.count_sessions()
        # Verify session22 still exists
        active = repo.get_active_sessions(1000, 100)
        ids = {s["id"] for s in active}
        assert "session22" in ids
