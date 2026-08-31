"""Unit tests for AppRepository."""

from __future__ import annotations

from contextlib import contextmanager
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert, select

from nomarr.helpers.dataclasses.app_dataclasses import (
    CapacityEstimate,
    ConfigOption,
    GpuResourceSnapshot,
    ModelVramLimit,
)
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.worker_claim_dataclass import (
    ClaimRemovalRequest,
    WorkerClaim,
    WorkerClaimIdentity,
)
from nomarr.helpers.exceptions import DuplicateEntityError
from nomarr.persistence.database.app_repo import AppRepository
from nomarr.persistence.models.health import Health
from nomarr.persistence.models.worker_restart_policy import WorkerRestartPolicy


def _make_identity(song_id: int) -> SongIdentity:
    return SongIdentity(
        library=LibraryIdentity(name="lib", root_path="/music"),
        normalized_path=f"artist/song{song_id}.flac",
    )


def _claim_env(pg_session):
    """Wire an AppRepository with in-memory song/library mocks for claims tests.

    Returns ``(repo, register, unregister)`` where ``register(song_id)`` registers
    a resolvable ``SongIdentity`` for that storage song id and ``unregister`` makes
    it missing again.  The mocks resolve both directions (natural identity ->
    storage id for acquisition, storage id -> natural identity for listing).
    """
    repo = AppRepository(
        pg_session,
        song_repo=MagicMock(),
        library_repo=MagicMock(),
        song_state_repo=MagicMock(),
    )
    song_repo = cast("MagicMock", repo._song_repo)
    library_repo = cast("MagicMock", repo._library_repo)
    lib_id = 100
    library_row = {"id": lib_id, "name": "lib", "path": "/music"}
    songs: dict[int, str] = {}

    def get_song_by_normalized_path(library_id: int, normalized_path: str) -> dict | None:
        for sid, path in songs.items():
            if path == normalized_path:
                return {"id": sid, "library_id": library_id, "normalized_path": normalized_path}
        return None

    def get_song(song_id: int) -> dict | None:
        if song_id not in songs:
            return None
        return {"id": song_id, "library_id": lib_id, "normalized_path": songs[song_id]}

    library_repo.get_library_by_natural_key.return_value = library_row
    library_repo.get_library.return_value = library_row
    song_repo.get_song_by_normalized_path.side_effect = get_song_by_normalized_path
    song_repo.get_song.side_effect = get_song

    def register(song_id: int) -> SongIdentity:
        identity = _make_identity(song_id)
        songs[song_id] = identity.normalized_path
        return identity

    def unregister(song_id: int) -> None:
        songs.pop(song_id, None)

    return repo, register, unregister


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
        """_get_meta should return meta by key."""
        repo = AppRepository(pg_session)
        repo._upsert_meta("version", {"value": {"major": 1}})
        result = repo._get_meta("version")
        assert result is not None
        assert result["key"] == "version"
        assert result["value"]["major"] == 1

    def test_get_meta_nonexistent(self, pg_session) -> None:
        """_get_meta should return None for missing key."""
        repo = AppRepository(pg_session)
        result = repo._get_meta("nonexistent")
        assert result is None

    def test_upsert_meta_insert(self, pg_session) -> None:
        """_upsert_meta should insert if not exists."""
        repo = AppRepository(pg_session)
        repo._upsert_meta("key1", {"value": {"data": "test"}})
        result = repo._get_meta("key1")
        assert result is not None

    def test_upsert_meta_update(self, pg_session) -> None:
        """_upsert_meta should update if exists."""
        repo = AppRepository(pg_session)
        repo._upsert_meta("key2", {"value": {"data": "old"}})
        repo._upsert_meta("key2", {"value": {"data": "new"}})
        result = repo._get_meta("key2")
        assert result is not None
        assert result["value"]["data"] == "new"

    def test_delete_meta(self, pg_session) -> None:
        """_delete_meta should remove the row."""
        repo = AppRepository(pg_session)
        repo._upsert_meta("key3", {"value": {}})
        repo._delete_meta("key3")
        result = repo._get_meta("key3")
        assert result is None

    def test_list_meta_keys_by_prefix(self, pg_session) -> None:
        """_list_meta_keys_by_prefix should return matching keys."""
        repo = AppRepository(pg_session)
        repo._upsert_meta("prefix_key1", {"value": {}})
        repo._upsert_meta("prefix_key2", {"value": {}})
        repo._upsert_meta("other_key", {"value": {}})
        result = repo._list_meta_keys_by_prefix("prefix_")
        assert len(result) == 2
        assert "prefix_key1" in result
        assert "prefix_key2" in result
        assert "other_key" not in result

    # ── Semantic meta helpers (config / schema / credentials) ──

    def test_get_config_option_nonexistent(self, pg_session) -> None:
        """get_config_option should return None for a missing key."""
        repo = AppRepository(pg_session)
        assert repo.get_config_option("config_missing") is None

    def test_set_and_get_config_option(self, pg_session) -> None:
        """set/get config option round-trips under the full storage key."""
        repo = AppRepository(pg_session)
        repo.set_config_option("config_library_path", "/music")
        result = repo.get_config_option("config_library_path")
        assert isinstance(result, ConfigOption)
        assert result.key == "config_library_path"
        assert result.value == "/music"

    def test_set_config_option_overwrites(self, pg_session) -> None:
        """set_config_option should overwrite an existing value."""
        repo = AppRepository(pg_session)
        repo.set_config_option("config_overwrite", "old")
        repo.set_config_option("config_overwrite", "new")
        result = repo.get_config_option("config_overwrite")
        assert result is not None
        assert result.value == "new"

    def test_list_config_options_returns_only_config_prefix(self, pg_session) -> None:
        """list_config_options should return only ``config_`` keys."""
        repo = AppRepository(pg_session)
        repo.set_config_option("config_a", "1")
        repo.set_config_option("config_b", {"nested": True})
        # A non-config key must not leak into the config listing.
        repo._upsert_meta("api_key", {"value": "secret"})
        results = repo.list_config_options()
        assert all(isinstance(c, ConfigOption) for c in results)
        by_key = {c.key: c.value for c in results}
        assert by_key == {"config_a": "1", "config_b": {"nested": True}}

    def test_remove_config_option(self, pg_session) -> None:
        """remove_config_option should delete the row."""
        repo = AppRepository(pg_session)
        repo.set_config_option("config_tmp", "x")
        repo.remove_config_option("config_tmp")
        assert repo.get_config_option("config_tmp") is None

    def test_get_schema_version_nonexistent(self, pg_session) -> None:
        """get_schema_version should return None when absent."""
        repo = AppRepository(pg_session)
        assert repo.get_schema_version() is None

    def test_set_and_get_schema_version(self, pg_session) -> None:
        """set/get schema version round-trips under the fixed ``version`` key."""
        repo = AppRepository(pg_session)
        repo.set_schema_version("1.0.0")
        assert repo.get_schema_version() == "1.0.0"

    def test_get_schema_version_coerces_stored_value_to_str(self, pg_session) -> None:
        """get_schema_version should coerce a non-string stored value to ``str``."""
        repo = AppRepository(pg_session)
        repo._upsert_meta("version", {"value": 7})
        assert repo.get_schema_version() == "7"

    def test_get_api_key_nonexistent(self, pg_session) -> None:
        """get_api_key should return None when not set."""
        repo = AppRepository(pg_session)
        assert repo.get_api_key() is None

    def test_set_and_get_api_key(self, pg_session) -> None:
        """set/get API key round-trips under the fixed ``api_key`` key."""
        repo = AppRepository(pg_session)
        repo.set_api_key("sk-test")
        assert repo.get_api_key() == "sk-test"

    def test_get_admin_password_hash_nonexistent(self, pg_session) -> None:
        """get_admin_password_hash should return None when not set."""
        repo = AppRepository(pg_session)
        assert repo.get_admin_password_hash() is None

    def test_set_and_get_admin_password_hash(self, pg_session) -> None:
        """set/get admin password hash round-trips under its fixed key."""
        repo = AppRepository(pg_session)
        repo.set_admin_password_hash("hashed-value")
        assert repo.get_admin_password_hash() == "hashed-value"

    # ── Calibration ────────────────────────────────────────────

    def test_get_calibration_version_nonexistent(self, pg_session) -> None:
        """get_calibration_version should return None when absent."""
        repo = AppRepository(pg_session)
        assert repo.get_calibration_version() is None

    def test_set_and_get_calibration_version(self, pg_session) -> None:
        """set/get calibration version round-trips under its fixed key."""
        repo = AppRepository(pg_session)
        repo.set_calibration_version("abc123")
        assert repo.get_calibration_version() == "abc123"

    def test_get_calibration_last_run_nonexistent(self, pg_session) -> None:
        """get_calibration_last_run should return None when absent."""
        repo = AppRepository(pg_session)
        assert repo.get_calibration_last_run() is None

    def test_set_and_get_calibration_last_run_stored_as_string(self, pg_session) -> None:
        """calibration last-run is stored as a string and read back as int (ms)."""
        repo = AppRepository(pg_session)
        repo.set_calibration_last_run("1700000000000")
        assert repo.get_calibration_last_run() == 1700000000000
        row = repo._get_meta("calibration_last_run")
        assert row is not None
        assert isinstance(row["value"], str)  # pinned: physical storage is a string

    def test_clear_calibration_metadata_removes_both_keys(self, pg_session) -> None:
        """clear_calibration_metadata should atomically delete both calibration keys."""
        repo = AppRepository(pg_session)
        repo.set_calibration_version("v1")
        repo.set_calibration_last_run("1700000000000")
        # Unrelated meta key must be left intact.
        repo.set_api_key("secret")

        removed = repo.clear_calibration_metadata()

        assert removed == 2
        assert repo.get_calibration_version() is None
        assert repo.get_calibration_last_run() is None
        assert repo.get_api_key() == "secret"

    def test_clear_calibration_metadata_noop_when_nothing_set(self, pg_session) -> None:
        """clear_calibration_metadata should return 0 when no keys exist."""
        repo = AppRepository(pg_session)
        assert repo.clear_calibration_metadata() == 0

    # ── VRAM limits ─────────────────────────────────────────────

    def test_get_model_vram_limit_nonexistent(self, pg_session) -> None:
        """get_model_vram_limit should return None when not measured."""
        repo = AppRepository(pg_session)
        assert repo.get_model_vram_limit("/models/a.pt") is None

    def test_set_and_get_model_vram_limit_stores_string_under_prefix(self, pg_session) -> None:
        """VRAM limits store a string byte count under the ``ml_model_vram:`` prefix."""
        repo = AppRepository(pg_session)
        repo.set_model_vram_limit("/models/a.pt", 8192)
        assert repo.get_model_vram_limit("/models/a.pt") == 8192
        row = repo._get_meta("ml_model_vram:/models/a.pt")
        assert row is not None
        assert row["key"] == "ml_model_vram:/models/a.pt"
        assert row["value"] == "8192"  # pinned: value stored as a string

    def test_list_model_vram_limits(self, pg_session) -> None:
        """list_model_vram_limits should strip the prefix and coerce byte counts."""
        repo = AppRepository(pg_session)
        repo.set_model_vram_limit("/models/a.pt", 4096)
        repo.set_model_vram_limit("/models/b.pt", 8192)
        # A non-VRAM meta key must not appear in the listing.
        repo._upsert_meta("ml_model_vram_other", {"value": "1"})

        result = repo.list_model_vram_limits()
        assert all(isinstance(m, ModelVramLimit) for m in result)
        by_path = {m.model_path: m.limit_bytes for m in result}
        assert by_path == {"/models/a.pt": 4096, "/models/b.pt": 8192}

    def test_clear_model_vram_limits_removes_all_vram_rows(self, pg_session) -> None:
        """clear_model_vram_limits should delete every ``ml_model_vram:`` row."""
        repo = AppRepository(pg_session)
        repo.set_model_vram_limit("/models/a.pt", 4096)
        repo.set_model_vram_limit("/models/b.pt", 8192)
        repo.set_api_key("secret")

        removed = repo.clear_model_vram_limits()

        assert removed == 2
        assert repo.list_model_vram_limits() == []
        assert repo.get_api_key() == "secret"

    def test_clear_model_vram_limits_noop_when_nothing_stored(self, pg_session) -> None:
        """clear_model_vram_limits should return 0 when no limits exist."""
        repo = AppRepository(pg_session)
        assert repo.clear_model_vram_limits() == 0

    # ── Capacity estimates ──────────────────────────────────────

    def test_get_capacity_estimate_nonexistent(self, pg_session) -> None:
        """get_capacity_estimate should return None when absent."""
        repo = AppRepository(pg_session)
        assert repo.get_capacity_estimate("hash1") is None

    def test_set_and_get_capacity_estimate(self, pg_session) -> None:
        """capacity estimate round-trips under the ``capacity_estimate:`` prefix."""
        repo = AppRepository(pg_session)
        estimate = CapacityEstimate(
            model_set_hash="hash1",
            measured_backbone_vram_mb=1024,
            estimated_worker_ram_mb=2048,
            gpu_capable=True,
            is_conservative=False,
        )
        repo.set_capacity_estimate(estimate)

        result = repo.get_capacity_estimate("hash1")
        assert result == estimate

    def test_capacity_estimate_stored_under_prefixed_key(self, pg_session) -> None:
        """capacity estimates are physically stored under ``capacity_estimate:<hash>``."""
        repo = AppRepository(pg_session)
        estimate = CapacityEstimate(
            model_set_hash="hash1",
            measured_backbone_vram_mb=512,
            estimated_worker_ram_mb=1024,
            gpu_capable=False,
        )
        repo.set_capacity_estimate(estimate)
        row = repo._get_meta("capacity_estimate:hash1")
        assert row is not None
        assert row["value"]["model_set_hash"] == "hash1"
        assert row["value"]["estimated_worker_ram_mb"] == 1024

    def test_remove_capacity_estimate(self, pg_session) -> None:
        """remove_capacity_estimate should delete the row."""
        repo = AppRepository(pg_session)
        repo.set_capacity_estimate(
            CapacityEstimate(
                model_set_hash="hash1",
                measured_backbone_vram_mb=512,
                estimated_worker_ram_mb=1024,
                gpu_capable=False,
            )
        )
        repo.remove_capacity_estimate("hash1")
        assert repo.get_capacity_estimate("hash1") is None

    # ── GPU resource snapshot ───────────────────────────────────

    def test_get_gpu_resource_snapshot_nonexistent(self, pg_session) -> None:
        """get_gpu_resource_snapshot should return None when absent."""
        repo = AppRepository(pg_session)
        assert repo.get_gpu_resource_snapshot() is None

    def test_set_and_get_gpu_resource_snapshot(self, pg_session) -> None:
        """GPU snapshot round-trips under the fixed ``gpu_resources`` key."""
        repo = AppRepository(pg_session)
        repo.set_gpu_resource_snapshot(GpuResourceSnapshot(gpu_available=True, error_summary=None))
        result = repo.get_gpu_resource_snapshot()
        assert result == GpuResourceSnapshot(gpu_available=True, error_summary=None)

    def test_set_and_get_gpu_resource_snapshot_with_error(self, pg_session) -> None:
        """GPU snapshot retains an error summary when the probe failed."""
        repo = AppRepository(pg_session)
        repo.set_gpu_resource_snapshot(GpuResourceSnapshot(gpu_available=False, error_summary="no vram"))
        result = repo.get_gpu_resource_snapshot()
        assert result == GpuResourceSnapshot(gpu_available=False, error_summary="no vram")

    # ── Worker system enabled ───────────────────────────────────

    def test_get_worker_system_enabled_nonexistent(self, pg_session) -> None:
        """get_worker_system_enabled should return None when not set."""
        repo = AppRepository(pg_session)
        assert repo.get_worker_system_enabled() is None

    def test_set_worker_system_enabled_true_stored_as_string(self, pg_session) -> None:
        """enabled=True is physically stored as the string ``true``."""
        repo = AppRepository(pg_session)
        repo.set_worker_system_enabled(True)
        assert repo.get_worker_system_enabled() is True
        row = repo._get_meta("worker_enabled")
        assert row is not None
        assert row["value"] == "true"  # pinned: physical string storage

    def test_set_worker_system_enabled_false_stored_as_string(self, pg_session) -> None:
        """enabled=False is physically stored as the string ``false``."""
        repo = AppRepository(pg_session)
        repo.set_worker_system_enabled(False)
        assert repo.get_worker_system_enabled() is False
        row = repo._get_meta("worker_enabled")
        assert row is not None
        assert row["value"] == "false"

    # ── _delete_meta_keys_atomic ────────────────────────────────

    def test_delete_meta_keys_atomic_removes_exact_keys_only(self, pg_session) -> None:
        """_delete_meta_keys_atomic deletes exactly the given keys and leaves others."""
        repo = AppRepository(pg_session)
        repo._upsert_meta("keep_1", {"value": "a"})
        repo._upsert_meta("drop_1", {"value": "b"})
        repo._upsert_meta("drop_2", {"value": "c"})
        repo._upsert_meta("keep_2", {"value": "d"})

        repo._delete_meta_keys_atomic(["drop_1", "drop_2"])

        assert repo._get_meta("drop_1") is None
        assert repo._get_meta("drop_2") is None
        assert repo._get_meta("keep_1") is not None
        assert repo._get_meta("keep_2") is not None

    def test_delete_meta_keys_atomic_empty_list_is_noop(self, pg_session) -> None:
        """_delete_meta_keys_atomic with no keys should not touch existing rows."""
        repo = AppRepository(pg_session)
        repo._upsert_meta("keep_1", {"value": "a"})
        repo._delete_meta_keys_atomic([])
        assert repo._get_meta("keep_1") is not None

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

    def test_acquire_claim_inserts_new_claim(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        song = register(1)
        claim = WorkerClaim(identity=WorkerClaimIdentity(song=song, worker_id="worker1"), claimed_at_ms=5000)

        assert repo._acquire_claim(claim, now_ms=5000, lease_ms=1000) is True
        claims = repo._list_claims()
        assert len(claims) == 1
        assert claims[0].identity.worker_id == "worker1"
        assert claims[0].identity.claim_type is None
        assert claims[0].claimed_at_ms == 5000
        assert repo._count_claims() == 1

    def test_acquire_claim_missing_song_returns_false(self, pg_session) -> None:
        repo, _, _ = _claim_env(pg_session)
        claim = WorkerClaim(
            identity=WorkerClaimIdentity(song=_make_identity(999), worker_id="worker1"),
            claimed_at_ms=5000,
        )
        assert repo._acquire_claim(claim, now_ms=5000, lease_ms=1000) is False

    def test_acquire_claim_active_contention_returns_false(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        song = register(1)
        first = WorkerClaim(identity=WorkerClaimIdentity(song=song, worker_id="worker1"), claimed_at_ms=4500)
        assert repo._acquire_claim(first, now_ms=5000, lease_ms=1000) is True
        # worker1's claim is still active (4500 >= 5000-1000) -> blocked.
        other = WorkerClaim(identity=WorkerClaimIdentity(song=song, worker_id="worker2"), claimed_at_ms=0)
        assert repo._acquire_claim(other, now_ms=5000, lease_ms=1000) is False
        assert repo._count_claims() == 1

    def test_acquire_claim_insert_only_never_replaces(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        song = register(1)
        first = WorkerClaim(identity=WorkerClaimIdentity(song=song, worker_id="worker1"), claimed_at_ms=1000)
        assert repo._acquire_claim(first, now_ms=1000, lease_ms=None) is True
        other = WorkerClaim(identity=WorkerClaimIdentity(song=song, worker_id="worker2"), claimed_at_ms=0)
        # lease_ms=None -> insert-only, so even an expired claim is not replaced.
        assert repo._acquire_claim(other, now_ms=5000, lease_ms=None) is False
        claims = repo._list_claims()
        assert len(claims) == 1
        assert claims[0].identity.worker_id == "worker1"

    def test_acquire_claim_replaces_expired_claim(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        song = register(1)
        first = WorkerClaim(identity=WorkerClaimIdentity(song=song, worker_id="worker1"), claimed_at_ms=1000)
        assert repo._acquire_claim(first, now_ms=1000, lease_ms=1000) is True
        thief = WorkerClaim(identity=WorkerClaimIdentity(song=song, worker_id="worker2"), claimed_at_ms=0)
        assert repo._acquire_claim(thief, now_ms=5000, lease_ms=1000) is True
        claims = repo._list_claims()
        assert len(claims) == 1
        assert claims[0].identity.worker_id == "worker2"
        assert claims[0].claimed_at_ms == 5000

    def test_acquire_claim_enforces_single_active_across_typed_and_untyped(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        song = register(1)
        untyped = WorkerClaim(identity=WorkerClaimIdentity(song=song, worker_id="worker1"), claimed_at_ms=4500)
        assert repo._acquire_claim(untyped, now_ms=5000, lease_ms=1000) is True
        # A typed claim on the same song conflicts with the active untyped claim.
        typed = WorkerClaim(
            identity=WorkerClaimIdentity(song=song, worker_id="worker2", claim_type="reconcile"),
            claimed_at_ms=0,
        )
        assert repo._acquire_claim(typed, now_ms=5000, lease_ms=1000) is False
        assert repo._count_claims() == 1

    def test_acquire_claim_cross_type_replaces_expired_claim(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        song = register(1)
        untyped = WorkerClaim(identity=WorkerClaimIdentity(song=song, worker_id="worker1"), claimed_at_ms=1000)
        assert repo._acquire_claim(untyped, now_ms=1000, lease_ms=1000) is True
        reconcile = WorkerClaim(
            identity=WorkerClaimIdentity(song=song, worker_id="worker2", claim_type="reconcile"),
            claimed_at_ms=0,
        )
        assert repo._acquire_claim(reconcile, now_ms=5000, lease_ms=1000) is True
        claims = repo._list_claims()
        assert len(claims) == 1
        assert claims[0].identity.claim_type == "reconcile"
        assert claims[0].identity.worker_id == "worker2"

    def test_remove_claim_exact_ownership(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        song = register(1)
        identity = WorkerClaimIdentity(song=song, worker_id="worker1")
        claim = WorkerClaim(identity=identity, claimed_at_ms=5000)
        assert repo._acquire_claim(claim, now_ms=5000, lease_ms=None) is True
        assert repo._remove_claim(identity) is True
        assert repo._remove_claim(identity) is False
        assert repo._count_claims() == 0

    def test_remove_claim_wrong_worker_leaves_claim(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        song = register(1)
        claim = WorkerClaim(identity=WorkerClaimIdentity(song=song, worker_id="worker1"), claimed_at_ms=5000)
        assert repo._acquire_claim(claim, now_ms=5000, lease_ms=None) is True
        wrong = WorkerClaimIdentity(song=song, worker_id="other")
        assert repo._remove_claim(wrong) is False
        assert repo._count_claims() == 1

    def test_remove_claims_by_worker(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        s1 = register(1)
        s2 = register(2)
        repo._acquire_claim(
            WorkerClaim(identity=WorkerClaimIdentity(song=s1, worker_id="w1"), claimed_at_ms=1000),
            now_ms=1000,
            lease_ms=None,
        )
        repo._acquire_claim(
            WorkerClaim(identity=WorkerClaimIdentity(song=s2, worker_id="w2"), claimed_at_ms=1000),
            now_ms=1000,
            lease_ms=None,
        )
        deleted = repo._remove_claims(ClaimRemovalRequest(worker_ids=("w1",)))
        assert deleted == 1
        assert repo._count_claims() == 1

    def test_remove_claims_by_song(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        s1 = register(1)
        s2 = register(2)
        repo._acquire_claim(
            WorkerClaim(identity=WorkerClaimIdentity(song=s1, worker_id="w1"), claimed_at_ms=1000),
            now_ms=1000,
            lease_ms=None,
        )
        repo._acquire_claim(
            WorkerClaim(identity=WorkerClaimIdentity(song=s2, worker_id="w2"), claimed_at_ms=1000),
            now_ms=1000,
            lease_ms=None,
        )
        deleted = repo._remove_claims(ClaimRemovalRequest(songs=(s1,)))
        assert deleted == 1
        assert repo._count_claims() == 1

    def test_remove_claims_stale_workers(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        s1 = register(1)
        s2 = register(2)
        repo._acquire_claim(
            WorkerClaim(identity=WorkerClaimIdentity(song=s1, worker_id="active"), claimed_at_ms=1000),
            now_ms=1000,
            lease_ms=None,
        )
        repo._acquire_claim(
            WorkerClaim(identity=WorkerClaimIdentity(song=s2, worker_id="dead"), claimed_at_ms=1000),
            now_ms=1000,
            lease_ms=None,
        )
        repo.upsert_health("active", {"status": "healthy", "last_seen": 5000})
        deleted = repo._remove_claims(ClaimRemovalRequest(stale_workers_before_ms=4000))
        assert deleted == 1
        assert {c.identity.worker_id for c in repo._list_claims()} == {"active"}

    def test_remove_claims_remove_missing_songs(self, pg_session) -> None:
        repo, register, unregister = _claim_env(pg_session)
        s1 = register(1)
        repo._acquire_claim(
            WorkerClaim(identity=WorkerClaimIdentity(song=s1, worker_id="w1"), claimed_at_ms=1000),
            now_ms=1000,
            lease_ms=None,
        )
        unregister(1)  # song no longer exists
        deleted = repo._remove_claims(ClaimRemovalRequest(remove_missing_songs=True))
        assert deleted == 1
        assert repo._count_claims() == 0

    def test_remove_claims_remove_completed_songs(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        s1 = register(1)
        repo._acquire_claim(
            WorkerClaim(identity=WorkerClaimIdentity(song=s1, worker_id="w1"), claimed_at_ms=1000),
            now_ms=1000,
            lease_ms=None,
        )
        repo._song_state_repo.list_songs_in_state.return_value = [1]
        deleted = repo._remove_claims(ClaimRemovalRequest(remove_completed_songs=True))
        assert deleted == 1
        assert repo._count_claims() == 0

    def test_remove_claims_remove_errored_songs(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        s1 = register(1)
        repo._acquire_claim(
            WorkerClaim(identity=WorkerClaimIdentity(song=s1, worker_id="w1"), claimed_at_ms=1000),
            now_ms=1000,
            lease_ms=None,
        )
        repo._song_state_repo.list_songs_in_state.return_value = [1]
        deleted = repo._remove_claims(ClaimRemovalRequest(remove_errored_songs=True))
        assert deleted == 1
        assert repo._count_claims() == 0

    def test_remove_claims_preserves_active_reconcile_claims(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        s1 = register(1)
        reconcile = WorkerClaim(
            identity=WorkerClaimIdentity(song=s1, worker_id="w1", claim_type="reconcile"),
            claimed_at_ms=1000,
        )
        assert repo._acquire_claim(reconcile, now_ms=1000, lease_ms=None) is True
        repo._song_state_repo.list_songs_in_state.return_value = [1]
        deleted = repo._remove_claims(ClaimRemovalRequest(remove_completed_songs=True))
        assert deleted == 0
        assert repo._count_claims() == 1

    def test_count_claims_direct_count(self, pg_session) -> None:
        repo, register, _ = _claim_env(pg_session)
        assert repo._count_claims() == 0
        s1 = register(1)
        repo._acquire_claim(
            WorkerClaim(identity=WorkerClaimIdentity(song=s1, worker_id="w1"), claimed_at_ms=1000),
            now_ms=1000,
            lease_ms=None,
        )
        assert repo._count_claims() == 1

    def test_list_claims_exposes_only_domain_values(self, pg_session) -> None:
        """list_claims returns resolvable rows as domain WorkerClaim values only.

        No storage keys, ids, or JSON payloads may leak across the boundary — the
        returned objects are frozen WorkerClaim domain values with a resolved
        SongIdentity (CONTRACTS.md).
        """
        repo, register, _ = _claim_env(pg_session)
        assert repo._list_claims() == []
        s1 = register(1)
        s2 = register(2)
        untyped = WorkerClaim(
            identity=WorkerClaimIdentity(song=s1, worker_id="w1"),
            claimed_at_ms=1000,
        )
        typed = WorkerClaim(
            identity=WorkerClaimIdentity(song=s2, worker_id="w2", claim_type="reconcile"),
            claimed_at_ms=2000,
        )
        assert repo._acquire_claim(untyped, now_ms=1000, lease_ms=None) is True
        assert repo._acquire_claim(typed, now_ms=2000, lease_ms=None) is True

        claims = repo._list_claims()
        assert len(claims) == 2
        by_song = {c.identity.song.normalized_path: c for c in claims}
        assert set(by_song) == {s1.normalized_path, s2.normalized_path}
        for c in claims:
            assert isinstance(c, WorkerClaim)
            assert isinstance(c.identity, WorkerClaimIdentity)
        assert by_song[s1.normalized_path].identity.worker_id == "w1"
        assert by_song[s1.normalized_path].identity.claim_type is None
        assert by_song[s1.normalized_path].claimed_at_ms == 1000
        assert by_song[s2.normalized_path].identity.worker_id == "w2"
        assert by_song[s2.normalized_path].identity.claim_type == "reconcile"
        assert by_song[s2.normalized_path].claimed_at_ms == 2000

    def test_list_claims_quarantines_orphan_rows(self, pg_session) -> None:
        """Unresolvable claim rows are quarantined, never surfaced to callers.

        A claim whose song identity can no longer be resolved (e.g. song removed)
        must not leak as a raw row; list_claims drops it while count_claims still
        reflects the persisted row (CONTRACTS.md orphan-quarantine rule).
        """
        repo, register, unregister = _claim_env(pg_session)
        s1 = register(1)
        assert (
            repo._acquire_claim(
                WorkerClaim(identity=WorkerClaimIdentity(song=s1, worker_id="w1"), claimed_at_ms=1000),
                now_ms=1000,
                lease_ms=None,
            )
            is True
        )
        assert len(repo._list_claims()) == 1

        # Song becomes unresolvable (deleted) → row becomes an orphan.
        unregister(1)
        assert repo._list_claims() == []
        assert repo._count_claims() == 1

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

    def test_delete_all_worker_claims(self, pg_session) -> None:
        """_delete_all_worker_claims should remove all claims."""
        repo, register, _ = _claim_env(pg_session)
        song = register(1)
        claim = WorkerClaim(identity=WorkerClaimIdentity(song=song, worker_id="worker1"), claimed_at_ms=1000)
        assert repo._acquire_claim(claim, now_ms=1000, lease_ms=None) is True
        repo._delete_all_worker_claims()
        assert repo._count_claims() == 0

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
