# mypy: disable-error-code=func-returns-value
"""Unit tests for ``AppDb`` delegation.

``AppDb`` is a thin facade over PostgreSQL repositories.  Each test verifies
that the correct repository method is called with the correct arguments and
that the return value is propagated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from nomarr.helpers.dataclasses.app_dataclasses import (
    ConfigOption,
    LockEntry,
    VramPromise,
    WorkerRestartPolicy,
)
from nomarr.helpers.dataclasses.session_dataclass import AuthSession
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.worker_claim_dataclass import (
    ClaimRemovalRequest,
    WorkerClaim,
    WorkerClaimIdentity,
)
from nomarr.helpers.dto.health_dto import WorkerHealth
from nomarr.persistence.api.application import AppDb
from nomarr.persistence.database.app_repo import AppRepository
from nomarr.persistence.database.pipeline_repo import PipelineRepository
from nomarr.persistence.database.song_state_repo import SongStateRepository
from nomarr.persistence.models.base import Base
from nomarr.persistence.models.vram_promise import VramPromise as VramPromiseModel

if TYPE_CHECKING:
    from nomarr.helpers.dto.repo_dto import (
        HealthRow,
    )

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_session() -> MagicMock:
    return MagicMock(spec=Session)


@pytest.fixture
def mock_app_repo() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_pipeline_repo() -> MagicMock:
    return MagicMock(spec=PipelineRepository)


@pytest.fixture
def mock_song_state_repo() -> MagicMock:
    return MagicMock()


@pytest.fixture
def app_db(
    mock_session: MagicMock,
    mock_app_repo: MagicMock,
    mock_song_state_repo: MagicMock,
    mock_pipeline_repo: MagicMock,
) -> AppDb:
    return AppDb(
        session=mock_session,
        app_repo=mock_app_repo,
        song_state_repo=mock_song_state_repo,
        pipeline_repo=mock_pipeline_repo,
    )


@pytest.fixture
def sqlite_app_db() -> AppDb:
    """End-to-end ``AppDb`` backed by a real in-memory SQLite engine.

    Only the ``vram_promises`` table is created (its columns are all
    portable — no JSONB, so no PostgreSQL-specific type patching is
    needed). The other repositories are mocked because the VRAM promise
    path exercises the real repo SQL layer, which is what catches bugs
    like the missing-``id`` insert failure.
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[VramPromiseModel.__table__])
    conn = engine.connect()
    conn.begin()
    conn.begin_nested()
    session = Session(bind=conn)
    app_db = AppDb(
        session=session,
        app_repo=AppRepository(session),
        song_state_repo=MagicMock(spec=SongStateRepository),
        pipeline_repo=MagicMock(spec=PipelineRepository),
    )
    try:
        yield app_db
    finally:
        session.close()
        conn.rollback()
        conn.close()
        engine.dispose()


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — File State Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbFileStateMethods:
    @pytest.mark.unit
    def test_get_file_states_delegates_to_song_state_repo(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        mock_song_state_repo.get_song_states.return_value = {"queued", "written"}

        result = app_db.song_state_membership(42)

        assert result == {"queued", "written"}
        mock_song_state_repo.get_song_states.assert_called_once_with(42)

    @pytest.mark.unit
    def test_get_file_states_returns_empty_set_when_no_state(
        self, app_db: AppDb, mock_song_state_repo: MagicMock
    ) -> None:
        mock_song_state_repo.get_song_states.return_value = set()

        result = app_db.song_state_membership(99)

        assert result == set()
        mock_song_state_repo.get_song_states.assert_called_once_with(99)

    @pytest.mark.unit
    def test_get_file_states_for_files_delegates(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        expected = {1: {"queued"}, 2: {"tagged", "queued"}}
        mock_song_state_repo.get_song_states_for_songs.return_value = expected

        result = app_db.song_state_memberships([1, 2])

        assert result == expected
        mock_song_state_repo.get_song_states_for_songs.assert_called_once_with([1, 2])

    @pytest.mark.unit
    def test_list_files_in_state_delegates(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        mock_song_state_repo.list_songs_in_state.return_value = [10, 20, 30]

        result = app_db.song_ids_with_state("queued", limit=50)

        assert result == [10, 20, 30]
        mock_song_state_repo.list_songs_in_state.assert_called_once_with("queued", limit=50)

    @pytest.mark.unit
    def test_list_files_in_state_without_limit(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        mock_song_state_repo.list_songs_in_state.return_value = [10]

        result = app_db.song_ids_with_state("tagged")

        assert result == [10]
        mock_song_state_repo.list_songs_in_state.assert_called_once_with("tagged", limit=None)

    @pytest.mark.unit
    def test_list_file_docs_in_state_delegates_to_pipeline_repo(
        self, app_db: AppDb, mock_pipeline_repo: MagicMock
    ) -> None:
        mock_pipeline_repo.list_song_docs_in_state.return_value = []

        result = app_db.songs_with_state("queued", limit=10)

        assert result == []
        mock_pipeline_repo.list_song_docs_in_state.assert_called_once_with("queued", limit=10)

    @pytest.mark.unit
    def test_list_file_docs_in_state_passes_activity_query_options(
        self, app_db: AppDb, mock_pipeline_repo: MagicMock
    ) -> None:
        mock_pipeline_repo.list_song_docs_in_state.return_value = []

        result = app_db.songs_with_state("processed", limit=1000, library_id=3, order_by_activity=True)

        assert result == []
        mock_pipeline_repo.list_song_docs_in_state.assert_called_once_with(
            "processed", limit=1000, library_id=3, order_by_activity=True
        )

    @pytest.mark.unit
    def test_count_songs_in_state_delegates(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        mock_song_state_repo.count_songs_in_state.return_value = 7

        result = app_db.count_songs_with_state("queued")

        assert result == 7
        mock_song_state_repo.count_songs_in_state.assert_called_once_with("queued")

    @pytest.mark.unit
    def test_add_file_states_assigns_each_file(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        app_db.set_song_state([1, 2, 3], "queued")

        mock_song_state_repo.set_state_for_songs.assert_called_once_with([1, 2, 3], "queued")

    @pytest.mark.unit
    def test_add_file_states_empty_list_no_calls(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        app_db.set_song_state([], "queued")

        mock_song_state_repo.set_state_for_songs.assert_called_once_with([], "queued")

    @pytest.mark.unit
    def test_replace_file_states_delegates_to_atomic_replacement(
        self, app_db: AppDb, mock_song_state_repo: MagicMock
    ) -> None:
        app_db.transition_song_states([1, 2], "not_processed", "processed")

        mock_song_state_repo.transition_state_for_songs.assert_called_once_with([1, 2], "not_processed", "processed")

    @pytest.mark.unit
    def test_remove_file_states_skips_empty_batch(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        app_db.clear_song_states([])

        mock_song_state_repo.remove_states_for_songs.assert_called_once_with([])

    @pytest.mark.unit
    def test_remove_file_states_delegates_non_empty(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        app_db.clear_song_states([10, 20])

        mock_song_state_repo.remove_states_for_songs.assert_called_once_with([10, 20])


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Lock Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbLockMethods:
    @pytest.mark.unit
    def test_get_lock_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected = LockEntry(
            lock_type="scan", resource_id="1", holder="w1", expires_at=0.0, acquired_at=0.0, status="active"
        )
        mock_app_repo.get_lock.return_value = {
            "key": "scan:1",
            "value": {"holder": "w1"},
        }

        result = app_db.get_lock("scan", "1")

        assert result == expected
        mock_app_repo.get_lock.assert_called_once_with("scan:1")

    @pytest.mark.unit
    def test_get_lock_returns_none_when_not_found(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_lock.return_value = None

        result = app_db.get_lock("scan", "missing")

        assert result is None

    @pytest.mark.unit
    def test_add_lock_delegates_to_insert_lock(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        lock = LockEntry("scan", "1", "w1", 123.0, 100.0, "active")

        app_db.add_lock(lock)

        mock_app_repo.insert_lock.assert_called_once_with(
            {
                "key": "scan:1",
                "value": {
                    "lock_type": "scan",
                    "resource_id": "1",
                    "holder": "w1",
                    "expires_at": 123.0,
                    "acquired_at": 100.0,
                    "status": "active",
                },
            }
        )

    @pytest.mark.unit
    def test_list_locks_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected = [
            LockEntry("a", "1", "", 0.0, 0.0, "active"),
            LockEntry("b", "2", "", 0.0, 0.0, "active"),
        ]
        mock_app_repo.list_locks.return_value = [
            {"key": "a:1", "value": {}},
            {"key": "b:2", "value": {}},
        ]

        result = app_db.list_locks()

        assert result == expected
        mock_app_repo.list_locks.assert_called_once_with()

    @pytest.mark.unit
    def test_remove_lock_delegates_to_release_lock(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.remove_lock("scan", "1")

        mock_app_repo.release_lock.assert_called_once_with("scan:1")

    @pytest.mark.unit
    def test_upsert_lock_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        lock = LockEntry("scan", "1", "w1", 123.0, 100.0, "active")

        app_db.upsert_lock(lock)

        mock_app_repo.upsert_lock.assert_called_once_with(
            "scan:1",
            {
                "value": {
                    "lock_type": "scan",
                    "resource_id": "1",
                    "holder": "w1",
                    "expires_at": 123.0,
                    "acquired_at": 100.0,
                    "status": "active",
                }
            },
        )

    @pytest.mark.unit
    def test_acquire_lock_returns_true_on_success(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.acquire_lock.return_value = True
        lock = LockEntry("scan", "1", "w1", 123.0, 100.0, "active")

        result = app_db.acquire_lock(lock)

        assert result is True
        mock_app_repo.acquire_lock.assert_called_once_with(
            "scan:1",
            {
                "value": {
                    "lock_type": "scan",
                    "resource_id": "1",
                    "holder": "w1",
                    "expires_at": 123.0,
                    "acquired_at": 100.0,
                    "status": "active",
                }
            },
        )

    def test_acquire_lock_returns_false_on_conflict(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.acquire_lock.return_value = False
        lock = LockEntry("scan", "1", "w1", 123.0, 100.0, "active")

        result = app_db.acquire_lock(lock)

        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Claim Methods
# ══════════════════════════════════════════════════════════════════════════════


def _claim_identity() -> WorkerClaimIdentity:
    return WorkerClaimIdentity(
        song=SongIdentity(
            library=LibraryIdentity(name="lib", root_path="/music"),
            normalized_path="artist/track.flac",
        ),
        worker_id="w1",
    )


def _claim() -> WorkerClaim:
    return WorkerClaim(identity=_claim_identity(), claimed_at_ms=5000)


def _removal_request() -> ClaimRemovalRequest:
    return ClaimRemovalRequest(worker_ids=("w1",))


class TestAppDbClaimMethods:
    @pytest.mark.unit
    def test_add_claim_delegates_with_default_now_and_no_lease(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo._acquire_claim.return_value = True
        claim = _claim()

        result = app_db.add_claim(claim)

        assert result is True
        mock_app_repo._acquire_claim.assert_called_once()
        call_kwargs = mock_app_repo._acquire_claim.call_args.kwargs
        assert call_kwargs["lease_ms"] is None
        assert call_kwargs["now_ms"] is not None and call_kwargs["now_ms"] > 0
        assert mock_app_repo._acquire_claim.call_args.args[0] == claim

    @pytest.mark.unit
    def test_add_claim_passes_now_and_lease(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo._acquire_claim.return_value = True
        claim = _claim()

        result = app_db.add_claim(claim, now_ms=1000, lease_ms=500)

        assert result is True
        mock_app_repo._acquire_claim.assert_called_once_with(claim, now_ms=1000, lease_ms=500)

    @pytest.mark.unit
    def test_remove_claim_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo._remove_claim.return_value = True
        identity = _claim_identity()

        result = app_db.remove_claim(identity)

        assert result is True
        mock_app_repo._remove_claim.assert_called_once_with(identity)

    @pytest.mark.unit
    def test_remove_claims_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo._remove_claims.return_value = 3
        request = _removal_request()

        result = app_db.remove_claims(request)

        assert result == 3
        mock_app_repo._remove_claims.assert_called_once_with(request)

    @pytest.mark.unit
    def test_list_claims_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected = [_claim()]
        mock_app_repo._list_claims.return_value = expected

        result = app_db.list_claims()

        assert result == expected
        mock_app_repo._list_claims.assert_called_once_with()

    @pytest.mark.unit
    def test_count_claims_delegates_without_calling_list(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo._count_claims.return_value = 7

        result = app_db.count_claims()

        assert result == 7
        mock_app_repo._count_claims.assert_called_once_with()
        mock_app_repo._list_claims.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Health Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbHealthMethods:
    @pytest.mark.unit
    def test_get_health_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected: HealthRow = {"id": 1, "worker_id": "ml-worker", "status": "healthy", "last_seen": 1000}
        mock_app_repo.get_health.return_value = expected

        result = app_db.get_health("ml-worker")

        assert result == WorkerHealth(worker_id="ml-worker", status="healthy", last_seen=1000)
        mock_app_repo.get_health.assert_called_once_with("ml-worker")

    @pytest.mark.unit
    def test_get_health_returns_none_when_not_found(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_health.return_value = None

        result = app_db.get_health("unknown")

        assert result is None

    @pytest.mark.unit
    def test_count_healthy_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.count_healthy.return_value = 3

        result = app_db.count_healthy()

        assert result == 3
        mock_app_repo.count_healthy.assert_called_once_with()

    @pytest.mark.unit
    def test_list_worker_health_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected: list[HealthRow] = [{"id": 1, "worker_id": "w1", "status": "healthy", "last_seen": 100}]
        mock_app_repo.list_worker_health.return_value = expected

        result = app_db.list_worker_health()

        assert result == [WorkerHealth(worker_id="w1", status="healthy", last_seen=100)]
        mock_app_repo.list_worker_health.assert_called_once_with()

    @pytest.mark.unit
    def test_update_health_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.update_health("ml-worker", status="healthy", last_seen=1234)

        mock_app_repo.update_health.assert_called_once_with("ml-worker", {"status": "healthy", "last_seen": 1234})

    @pytest.mark.unit
    def test_upsert_health_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.upsert_health("ml-worker", status="healthy", last_seen=1234)

        mock_app_repo.upsert_health.assert_called_once_with("ml-worker", {"status": "healthy", "last_seen": 1234})


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Migration Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbMigrationMethods:
    @pytest.mark.unit
    def test_upsert_migration_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.upsert_migration("001_initial", {"applied_at": 1000})

        mock_app_repo.upsert_migration.assert_called_once_with("001_initial", {"applied_at": 1000})

    @pytest.mark.unit
    def test_list_migrations_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected = [{"name": "001_initial", "applied_at": 1000}]
        mock_app_repo.list_migrations.return_value = expected

        result = app_db.list_migrations()

        assert result == expected
        mock_app_repo.list_migrations.assert_called_once_with()


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — VRAM Promise Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbVramPromiseMethods:
    @pytest.mark.unit
    def test_list_vram_promises_returns_domain_values(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected = [
            VramPromise(
                worker_id="w1",
                pid=1,
                model_path="/m.onnx",
                promised_mb=512,
                total_mb=8000,
                used_mb=1000,
            )
        ]
        mock_app_repo.get_vram_promises.return_value = expected

        result = app_db.list_vram_promises()

        assert result == expected
        mock_app_repo.get_vram_promises.assert_called_once_with()

    @pytest.mark.unit
    def test_count_vram_promises_delegates_to_count(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.count_vram_promises.return_value = 3

        assert app_db.count_vram_promises() == 3
        mock_app_repo.count_vram_promises.assert_called_once_with()
        mock_app_repo.get_vram_promises.assert_not_called()

    @pytest.mark.unit
    def test_promise_vram_delegates_to_insert(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.promise_vram(
            worker_id="w1",
            pid=1,
            model_path="/m.onnx",
            promised_mb=512.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )

        mock_app_repo.insert_vram_promise.assert_called_once_with(
            worker_id="w1",
            pid=1,
            model_path="/m.onnx",
            promised_mb=512.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )

    @pytest.mark.unit
    def test_promise_vram_inserts_end_to_end(self, sqlite_app_db: AppDb) -> None:
        sqlite_app_db.promise_vram(
            worker_id="worker:1",
            pid=999,
            model_path="/models/a.onnx",
            promised_mb=512.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )

        promises = sqlite_app_db.list_vram_promises()
        assert promises == [
            VramPromise(
                worker_id="worker:1",
                pid=999,
                model_path="/models/a.onnx",
                promised_mb=512.0,
                total_mb=8000.0,
                used_mb=1000.0,
            )
        ]

    @pytest.mark.unit
    def test_release_vram_delegates_to_repo(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.delete_vram_promise_by_worker_model.return_value = 1

        assert app_db.release_vram(worker_id="w1", model_path="/m.onnx") == 1
        mock_app_repo.delete_vram_promise_by_worker_model.assert_called_once_with("w1", "/m.onnx")

    @pytest.mark.unit
    def test_release_vram_removes_promise_end_to_end(self, sqlite_app_db: AppDb) -> None:
        sqlite_app_db.promise_vram(
            worker_id="worker:1",
            pid=1,
            model_path="/models/a.onnx",
            promised_mb=512.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )
        sqlite_app_db.promise_vram(
            worker_id="worker:1",
            pid=2,
            model_path="/models/a.onnx",
            promised_mb=256.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )
        sqlite_app_db.promise_vram(
            worker_id="worker:2",
            pid=3,
            model_path="/models/b.onnx",
            promised_mb=128.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )

        sqlite_app_db.release_vram(worker_id="worker:1", model_path="/models/a.onnx")

        remaining = sqlite_app_db.list_vram_promises()
        assert len(remaining) == 1
        assert remaining[0].worker_id == "worker:2"

    @pytest.mark.unit
    def test_release_all_for_worker_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.delete_vram_promises_by_worker.return_value = 3

        assert app_db.release_all_for_worker(worker_id="w1") == 3
        mock_app_repo.delete_vram_promises_by_worker.assert_called_once_with("w1")

    @pytest.mark.unit
    def test_release_all_for_worker_removes_matching_end_to_end(self, sqlite_app_db: AppDb) -> None:
        for worker_id, model_path in (
            ("worker:1", "/models/a.onnx"),
            ("worker:1", "/models/b.onnx"),
            ("worker:2", "/models/c.onnx"),
        ):
            sqlite_app_db.promise_vram(
                worker_id=worker_id,
                pid=1,
                model_path=model_path,
                promised_mb=512.0,
                total_mb=8000.0,
                used_mb=1000.0,
            )

        sqlite_app_db.release_all_for_worker(worker_id="worker:1")

        remaining = sqlite_app_db.list_vram_promises()
        assert len(remaining) == 1
        assert remaining[0].worker_id == "worker:2"


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Worker Restart Policy Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbWorkerRestartPolicyMethods:
    @pytest.mark.unit
    def test_get_worker_restart_policy_maps_storage_to_domain(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_worker_restart_policy.return_value = {
            "restart_count": 3,
            "last_restart_wall_ms": 10,
            "failure_reason": None,
        }

        result = app_db.get_worker_restart_policy("ml-worker")

        assert result == WorkerRestartPolicy(restart_count=3, last_restart_wall_ms=10)

    @pytest.mark.unit
    def test_get_worker_restart_policy_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_worker_restart_policy.return_value = None

        assert app_db.get_worker_restart_policy("unknown") is None

    @pytest.mark.unit
    def test_record_worker_restart_persists_domain_fields(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_worker_restart_policy.return_value = None

        app_db.record_worker_restart("ml-worker")

        mock_app_repo.upsert_worker_restart_policy.assert_called_once()
        component_id, fields = mock_app_repo.upsert_worker_restart_policy.call_args.args
        assert component_id == "ml-worker"
        assert fields["restart_count"] == 1
        assert fields["last_restart_wall_ms"] is not None

    @pytest.mark.unit
    def test_mark_worker_restart_failed_persists_reason(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_worker_restart_policy.return_value = None

        app_db.mark_worker_restart_failed("ml-worker", "crash loop")

        _, fields = mock_app_repo.upsert_worker_restart_policy.call_args.args
        assert fields["failure_reason"] == "crash loop"
        assert fields["failed_at_wall_ms"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Session Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbSessionMethods:
    @pytest.mark.unit
    def test_save_session_maps_domain_object_to_storage(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        session = AuthSession(token="s1", data={"user": "admin"}, expires_at=9.999)

        app_db.save_session(session)

        mock_app_repo.insert_session.assert_called_once_with(
            [{"id": "s1", "data": {"user": "admin"}, "expires_at": 9999}]
        )

    @pytest.mark.unit
    def test_delete_session_delegates_by_token(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.delete_session("s1")

        mock_app_repo.delete_session.assert_called_once_with("s1")

    @pytest.mark.unit
    def test_find_expired_sessions_maps_repository_rows(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_sessions_expiring_before.return_value = [
            {"id": "s1", "data": {"user": "admin"}, "expires_at": 9999}
        ]

        result = app_db.find_expired_sessions(10.0)

        assert result == [AuthSession(token="s1", data={"user": "admin"}, expires_at=9.999)]
        mock_app_repo.get_sessions_expiring_before.assert_called_once_with(10000)

    @pytest.mark.unit
    def test_delete_sessions_maps_domain_objects_to_tokens(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        sessions = [AuthSession(token="s1", expires_at=1.0), AuthSession(token="s2", expires_at=2.0)]

        app_db.delete_sessions(sessions)

        mock_app_repo.delete_sessions_by_ids.assert_called_once_with(["s1", "s2"])

    @pytest.mark.unit
    def test_find_active_sessions_maps_repository_rows(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_active_sessions.return_value = [{"id": "s1", "data": {}, "expires_at": 1000}]

        result = app_db.find_active_sessions(1.0)

        assert result == [AuthSession(token="s1", expires_at=1.0)]
        mock_app_repo.get_active_sessions.assert_called_once_with(1000)


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Config/Meta Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbConfigMetaMethods:
    @pytest.mark.unit
    def test_get_config_option_prepends_config_prefix(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected: ConfigOption = ConfigOption(key="config_scan_interval", value={"interval": 300})
        mock_app_repo.get_config_option.return_value = expected

        result = app_db.get_config_option("scan_interval")

        assert result == expected
        mock_app_repo.get_config_option.assert_called_once_with("config_scan_interval")

    @pytest.mark.unit
    def test_get_config_option_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_config_option.return_value = None

        result = app_db.get_config_option("missing_key")

        assert result is None
        mock_app_repo.get_config_option.assert_called_once_with("config_missing_key")

    @pytest.mark.unit
    def test_set_config_option_delegates_with_scalar(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.set_config_option("scan_interval", "60")

        mock_app_repo.set_config_option.assert_called_once_with("config_scan_interval", "60")

    @pytest.mark.unit
    def test_set_config_option_rejects_storage_payload(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        with pytest.raises(ValueError):
            app_db.set_config_option("scan_interval", {"value": 60})
        mock_app_repo.set_config_option.assert_not_called()

    @pytest.mark.unit
    def test_list_config_options_delegates_no_prefix(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.list_config_options()

        mock_app_repo.list_config_options.assert_called_once_with()

    @pytest.mark.unit
    def test_remove_config_option_prepends_config_prefix(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.remove_config_option("scan_interval")

        mock_app_repo.remove_config_option.assert_called_once_with("config_scan_interval")

    @pytest.mark.unit
    def test_get_schema_version_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_schema_version.return_value = "2.5.0"

        result = app_db.get_schema_version()

        assert result == "2.5.0"
        mock_app_repo.get_schema_version.assert_called_once_with()

    @pytest.mark.unit
    def test_set_schema_version_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.set_schema_version("2.5.1")

        mock_app_repo.set_schema_version.assert_called_once_with("2.5.1")

    @pytest.mark.unit
    def test_no_generic_meta_surface(self, app_db: AppDb) -> None:
        for forbidden in (
            "get_meta",
            "upsert_meta",
            "delete_meta",
            "list_meta_keys_by_prefix",
            "update_config_option",
        ):
            assert not hasattr(app_db, forbidden), f"AppDb must not expose '{forbidden}'"


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Surface Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbSurface:
    @pytest.mark.unit
    def test_exposes_maintenance_surface(self, app_db: AppDb) -> None:
        assert hasattr(app_db.maintenance, "delete_all_worker_claims")
        assert hasattr(app_db, "truncate_health")
        assert hasattr(app_db, "truncate_song_state_edges")

    @pytest.mark.unit
    def test_maintenance_methods_not_on_app_db(self, app_db: AppDb) -> None:
        assert not hasattr(app_db, "get_state_edges_for_files")
        assert not hasattr(app_db, "count_pipeline_states")
        assert not hasattr(app_db, "claim_file")
        assert not hasattr(app_db, "list_libraries_in_pipeline_state")
        assert not hasattr(app_db, "count_calibration_states")
        # Legacy claims surface removed: all-claims deletion lives only under
        # maintenance, and the old intent methods are gone.
        assert not hasattr(app_db, "truncate_worker_claims")
        assert not hasattr(app_db, "claim_song")
        assert not hasattr(app_db, "steal_claim")
        assert not hasattr(app_db, "release_claim")
        assert not hasattr(app_db, "remove_claim_by_song")


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Maintenance Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbMaintenanceMethods:
    @pytest.mark.unit
    def test_truncate_file_state_edges_delegates(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        app_db.truncate_song_state_edges()

        mock_song_state_repo.truncate_assignments.assert_called_once_with()

    @pytest.mark.unit
    def test_truncate_worker_claims_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.maintenance.delete_all_worker_claims()

        mock_app_repo._delete_all_worker_claims.assert_called_once_with()

    @pytest.mark.unit
    def test_truncate_health_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.truncate_health()

        mock_app_repo.truncate_health.assert_called_once_with()
