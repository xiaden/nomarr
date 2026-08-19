# mypy: disable-error-code=func-returns-value
"""Unit tests for ``AppDb`` delegation.

``AppDb`` is a thin facade over PostgreSQL repositories.  Each test verifies
that the correct repository method is called with the correct arguments and
that the return value is propagated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from nomarr.helpers.dataclasses.app_dataclasses import ConfigOption, LockEntry
from nomarr.persistence.api.application import AppDb
from nomarr.persistence.database.app_repo import AppRepository
from nomarr.persistence.database.library_repo import LibraryRepository
from nomarr.persistence.database.pipeline_repo import PipelineRepository
from nomarr.persistence.database.song_state_repo import SongStateRepository
from nomarr.persistence.models.base import Base
from nomarr.persistence.models.vram_promise import VramPromise

if TYPE_CHECKING:
    from nomarr.helpers.dto.repo_dto import (
        HealthRow,
        SessionRow,
        SongRow,
        WorkerClaimRow,
    )

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_session() -> MagicMock:
    return MagicMock(spec=Session)


@pytest.fixture
def mock_app_repo() -> MagicMock:
    # Plain MagicMock: the AppDb facade still calls file-vocab repo methods
    # (e.g. delete_claims_for_songs) that no longer exist on the song-vocab
    # AppRepository. Those facade methods are renamed in Plan D/E; until then
    # the mock must accept both vocabularies.
    return MagicMock()


@pytest.fixture
def mock_library_repo() -> MagicMock:
    return MagicMock(spec=LibraryRepository)


@pytest.fixture
def mock_song_state_repo() -> MagicMock:
    # Plain MagicMock: the AppDb facade still calls file-vocab repo methods
    # (get_song_state, list_songs_in_state, ...) that no longer exist on the
    # song-vocab SongStateRepository. Those facade methods are renamed in
    # Plan D/E; until then the mock must accept both vocabularies.
    return MagicMock()


@pytest.fixture
def mock_pipeline_repo() -> MagicMock:
    # Plain MagicMock: the AppDb facade still calls the file-vocab
    # list_song_docs_in_state which no longer exists on the song-vocab
    # PipelineRepository (list_song_docs_in_state). Renamed in Plan D/E;
    # until then the mock must accept both vocabularies.
    return MagicMock()


@pytest.fixture
def app_db(
    mock_session: MagicMock,
    mock_app_repo: MagicMock,
    mock_library_repo: MagicMock,
    mock_song_state_repo: MagicMock,
    mock_pipeline_repo: MagicMock,
) -> AppDb:
    return AppDb(
        session=mock_session,
        app_repo=mock_app_repo,
        library_repo=mock_library_repo,
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
    Base.metadata.create_all(engine, tables=[VramPromise.__table__])
    conn = engine.connect()
    conn.begin()
    conn.begin_nested()
    session = Session(bind=conn)
    app_db = AppDb(
        session=session,
        app_repo=AppRepository(session),
        library_repo=MagicMock(spec=LibraryRepository),
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

        result = app_db.get_song_states(42)

        assert result == {"queued", "written"}
        mock_song_state_repo.get_song_states.assert_called_once_with(42)

    @pytest.mark.unit
    def test_get_file_states_returns_empty_set_when_no_state(
        self, app_db: AppDb, mock_song_state_repo: MagicMock
    ) -> None:
        mock_song_state_repo.get_song_states.return_value = set()

        result = app_db.get_song_states(99)

        assert result == set()
        mock_song_state_repo.get_song_states.assert_called_once_with(99)

    @pytest.mark.unit
    def test_get_file_states_for_files_delegates(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        expected = {1: {"queued"}, 2: {"tagged", "queued"}}
        mock_song_state_repo.get_song_states_for_songs.return_value = expected

        result = app_db.get_song_states_for_songs([1, 2])

        assert result == expected
        mock_song_state_repo.get_song_states_for_songs.assert_called_once_with([1, 2])

    @pytest.mark.unit
    def test_list_files_in_state_delegates(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        mock_song_state_repo.list_songs_in_state.return_value = [10, 20, 30]

        result = app_db.list_songs_in_state("queued", limit=50)

        assert result == [10, 20, 30]
        mock_song_state_repo.list_songs_in_state.assert_called_once_with("queued", limit=50)

    @pytest.mark.unit
    def test_list_files_in_state_without_limit(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        mock_song_state_repo.list_songs_in_state.return_value = [10]

        result = app_db.list_songs_in_state("tagged")

        assert result == [10]
        mock_song_state_repo.list_songs_in_state.assert_called_once_with("tagged", limit=None)

    @pytest.mark.unit
    def test_list_file_docs_in_state_delegates_to_pipeline_repo(
        self, app_db: AppDb, mock_pipeline_repo: MagicMock
    ) -> None:
        expected: list[SongRow] = []
        mock_pipeline_repo.list_song_docs_in_state.return_value = expected

        result = app_db.list_song_docs_in_state("queued", limit=10)

        assert result == expected
        mock_pipeline_repo.list_song_docs_in_state.assert_called_once_with("queued", limit=10)

    @pytest.mark.unit
    def test_count_songs_in_state_delegates(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        mock_song_state_repo.count_songs_in_state.return_value = 7

        result = app_db.count_songs_in_state("queued")

        assert result == 7
        mock_song_state_repo.count_songs_in_state.assert_called_once_with("queued")

    @pytest.mark.unit
    def test_add_file_states_assigns_each_file(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        app_db.add_song_states([1, 2, 3], "queued")

        mock_song_state_repo.assign_states.assert_called_once_with([1, 2, 3], "queued")

    @pytest.mark.unit
    def test_add_file_states_empty_list_no_calls(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        app_db.add_song_states([], "queued")

        mock_song_state_repo.assign_states.assert_not_called()

    @pytest.mark.unit
    def test_replace_file_states_delegates_to_atomic_replacement(
        self, app_db: AppDb, mock_song_state_repo: MagicMock
    ) -> None:
        app_db.replace_song_states([1, 2], "processing")

        mock_song_state_repo.replace_state_for_songs.assert_called_once_with([1, 2], "processing")

    @pytest.mark.unit
    def test_remove_file_states_skips_empty_batch(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        app_db.remove_song_states([])

        mock_song_state_repo.remove_states_for_songs.assert_not_called()

    @pytest.mark.unit
    def test_remove_file_states_delegates_non_empty(self, app_db: AppDb, mock_song_state_repo: MagicMock) -> None:
        app_db.remove_song_states([10, 20])

        mock_song_state_repo.remove_states_for_songs.assert_called_once_with([10, 20])


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Pipeline State Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbPipelineStateMethods:
    @pytest.mark.unit
    def test_get_pipeline_state_delegates_to_library_repo(self, app_db: AppDb, mock_library_repo: MagicMock) -> None:
        expected = {
            "scan_state": "scanning",
            "ml_state": "not_ML_processed",
            "calibration_state": "not_calibrated",
            "tag_write_state": "not_written",
        }
        mock_library_repo.get_pipeline_state.return_value = expected

        result = app_db.get_pipeline_state(5)

        assert result == expected
        mock_library_repo.get_pipeline_state.assert_called_once_with(5)

    @pytest.mark.unit
    def test_get_libraries_in_axis_state_delegates(self, app_db: AppDb, mock_library_repo: MagicMock) -> None:
        mock_library_repo.get_libraries_in_axis_state.return_value = [1, 3, 7]

        result = app_db.get_libraries_in_axis_state("scan_state", "scanning")

        assert result == [1, 3, 7]
        mock_library_repo.get_libraries_in_axis_state.assert_called_once_with("scan_state", "scanning")

    @pytest.mark.unit
    def test_upsert_pipeline_state_delegates(self, app_db: AppDb, mock_pipeline_repo: MagicMock) -> None:
        app_db.upsert_pipeline_state(5, "scan_state", {"state": "scanning"})

        mock_pipeline_repo.upsert_pipeline_state.assert_called_once_with(5, "scan_state", {"state": "scanning"})


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Lock Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbLockMethods:
    @pytest.mark.unit
    def test_get_lock_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected: LockEntry = LockEntry(key="scan:1", value={"owner": "w1"})
        mock_app_repo.get_lock.return_value = {"key": "scan:1", "value": {"owner": "w1"}}

        result = app_db.get_lock("scan:1")

        assert result == expected
        mock_app_repo.get_lock.assert_called_once_with("scan:1")

    @pytest.mark.unit
    def test_get_lock_returns_none_when_not_found(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_lock.return_value = None

        result = app_db.get_lock("missing")

        assert result is None

    @pytest.mark.unit
    def test_add_lock_delegates_to_insert_lock(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        payload = {"document_reference": "scan:1", "holder": "w1", "expires_at": 123}
        mock_app_repo.insert_lock.return_value = "scan:1"

        result = app_db.add_lock(payload)

        assert result == "scan:1"
        mock_app_repo.insert_lock.assert_called_once_with({"key": "scan:1", "value": payload})

    @pytest.mark.unit
    def test_list_locks_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected: list[LockEntry] = [LockEntry(key="a", value={}), LockEntry(key="b", value={})]
        mock_app_repo.list_locks.return_value = [{"key": "a", "value": {}}, {"key": "b", "value": {}}]

        result = app_db.list_locks()

        assert result == expected
        mock_app_repo.list_locks.assert_called_once_with()

    @pytest.mark.unit
    def test_remove_lock_delegates_to_release_lock(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.remove_lock("scan:1")

        mock_app_repo.release_lock.assert_called_once_with("scan:1")

    @pytest.mark.unit
    def test_upsert_lock_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        payload = {"owner": "w1"}

        app_db.upsert_lock("scan:1", payload)

        mock_app_repo.upsert_lock.assert_called_once_with("scan:1", {"value": payload})

    @pytest.mark.unit
    def test_acquire_lock_returns_true_on_success(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.acquire_lock.return_value = True

        result = app_db.acquire_lock("scan:1", {"owner": "w1"})

        assert result is True
        mock_app_repo.acquire_lock.assert_called_once_with("scan:1", {"value": {"owner": "w1"}})

    @pytest.mark.unit
    def test_acquire_lock_returns_false_on_conflict(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.acquire_lock.return_value = False

        result = app_db.acquire_lock("scan:1", {"owner": "w1"})

        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Claim Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbClaimMethods:
    @pytest.mark.unit
    def test_claim_song_builds_payload_and_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.insert_worker_claim.return_value = 42
        app_db._library_repo = MagicMock()
        app_db._library_repo.get_song.return_value = {"id": 1}

        result = app_db.claim_song(1, "w1")

        assert result == 42
        payload = mock_app_repo.insert_worker_claim.call_args.args[0]
        assert payload["key"] == "claim_1"
        assert payload["worker_id"] == "w1"
        assert payload["file_id"] == 1
        assert payload["claimed_at"] > 0

    @pytest.mark.unit
    def test_remove_claim_delegates_to_release_claim(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.remove_claim("w1", 42)

        mock_app_repo.release_claim.assert_called_once_with("w1", 42, None)

    @pytest.mark.unit
    def test_release_claim_is_alias_for_remove_claim(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.release_claim("w1", 42)

        mock_app_repo.release_claim.assert_called_once_with("w1", 42, None)

    @pytest.mark.unit
    def test_remove_claims_combines_worker_and_file_removals(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.delete_claims.return_value = 3

        result = app_db.remove_claims(worker_ids=["w1"], song_ids=[1, 2])

        assert result == 3
        mock_app_repo.delete_claims.assert_called_once_with(worker_ids=["w1"], song_ids=[1, 2])

    @pytest.mark.unit
    def test_remove_claims_worker_ids_only(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.delete_claims.return_value = 4

        result = app_db.remove_claims(worker_ids=["w1", "w2"])

        assert result == 4
        mock_app_repo.delete_claims.assert_called_once_with(worker_ids=["w1", "w2"], song_ids=None)

    @pytest.mark.unit
    def test_remove_claims_file_ids_only(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.delete_claims.return_value = 1

        result = app_db.remove_claims(song_ids=[10])

        assert result == 1
        mock_app_repo.delete_claims.assert_called_once_with(worker_ids=None, song_ids=[10])

    @pytest.mark.unit
    def test_remove_claims_no_filters_returns_zero(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.delete_claims.return_value = 0

        result = app_db.remove_claims()

        assert result == 0
        mock_app_repo.delete_claims.assert_called_once_with(worker_ids=None, song_ids=None)

    @pytest.mark.unit
    def test_list_claims_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected: list[WorkerClaimRow] = []
        mock_app_repo.list_claims.return_value = expected

        result = app_db.list_claims()

        assert result == expected
        mock_app_repo.list_claims.assert_called_once_with()


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Health Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbHealthMethods:
    @pytest.mark.unit
    def test_get_health_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected: HealthRow = {"id": 1, "worker_id": "ml-worker", "status": "healthy", "last_seen": 1000}
        mock_app_repo.get_health.return_value = expected

        result = app_db.get_health("ml-worker")

        assert result == expected
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

        assert result == expected
        mock_app_repo.list_worker_health.assert_called_once_with()

    @pytest.mark.unit
    def test_update_health_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        fields = {"status": "healthy", "heartbeat_ms": 1234}

        app_db.update_health("ml-worker", fields)

        mock_app_repo.update_health.assert_called_once_with("ml-worker", fields)

    @pytest.mark.unit
    def test_upsert_health_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        fields = {"status": "healthy"}

        app_db.upsert_health("ml-worker", fields)

        mock_app_repo.upsert_health.assert_called_once_with("ml-worker", fields)


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
    def test_add_vram_promise_delegates_to_upsert(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        payload = {"id": 1, "worker_id": "w1", "promised_mb": 512}

        app_db.add_vram_promise(payload)

        mock_app_repo.upsert_vram_promise.assert_called_once_with(payload)

    @pytest.mark.unit
    def test_list_vram_promises_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected = [{"id": 1, "worker_id": "w1"}]
        mock_app_repo.get_vram_promises.return_value = expected

        result = app_db.list_vram_promises()

        assert result == expected
        mock_app_repo.get_vram_promises.assert_called_once_with()

    @pytest.mark.unit
    def test_remove_vram_promise_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.remove_vram_promise(42)

        mock_app_repo.delete_vram_promise.assert_called_once_with(42)

    @pytest.mark.unit
    def test_count_vram_promises_returns_length(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_vram_promises.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]

        result = app_db.count_vram_promises()

        assert result == 3

    @pytest.mark.unit
    def test_count_vram_promises_empty(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_vram_promises.return_value = []

        result = app_db.count_vram_promises()

        assert result == 0

    @pytest.mark.unit
    def test_promise_vram_delegates_to_upsert(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.promise_vram(
            worker_id="w1",
            pid=1,
            model_path="/m.onnx",
            promised_mb=512.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )

        # Payload must NOT contain an 'id' — the repo plain-inserts and the
        # autoincrement column assigns it.
        mock_app_repo.upsert_vram_promise.assert_called_once_with(
            {
                "worker_id": "w1",
                "pid": 1,
                "model_path": "/m.onnx",
                "promised_mb": 512.0,
                "total_mb": 8000.0,
                "used_mb": 1000.0,
            }
        )

    @pytest.mark.unit
    def test_promise_vram_inserts_end_to_end(self, sqlite_app_db: AppDb) -> None:
        """promise_vram must insert a real row through the repo SQL layer.

        Regression test for the latent KeyError: the old ``upsert_vram_promise``
        unconditionally read ``payload["id"]``, which promise_vram's payload
        does not contain.
        """
        sqlite_app_db.promise_vram(
            worker_id="worker:1",
            pid=999,
            model_path="/models/a.onnx",
            promised_mb=512.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )

        promises = sqlite_app_db.list_vram_promises()
        assert len(promises) == 1
        row = promises[0]
        assert row["id"] is not None
        assert row["worker_id"] == "worker:1"
        assert row["pid"] == 999
        assert row["model_path"] == "/models/a.onnx"
        assert row["promised_mb"] == 512.0
        assert row["total_mb"] == 8000.0
        assert row["used_mb"] == 1000.0

    @pytest.mark.unit
    def test_release_vram_delegates_to_repo(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.release_vram(worker_id="w1", model_path="/m.onnx")

        mock_app_repo.delete_vram_promise_by_worker_model.assert_called_once_with("w1", "/m.onnx")

    @pytest.mark.unit
    def test_release_vram_removes_promise_end_to_end(self, sqlite_app_db: AppDb) -> None:
        """promise then release → zero rows remain for that worker+model.

        Two promises are inserted for the SAME pair: the absorbed adapter's
        release only deleted the first match it found (list-then-break), so
        this is a deterministic regression guard for the atomic delete.
        """
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
        assert remaining[0]["worker_id"] == "worker:2"

    @pytest.mark.unit
    def test_release_all_for_worker_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_vram_promises.return_value = [
            {"id": 1, "worker_id": "w1"},
            {"id": 2, "worker_id": "w2"},
            {"id": 3, "worker_id": "w1"},
        ]

        app_db.release_all_for_worker(worker_id="w1")

        assert mock_app_repo.delete_vram_promise.call_args_list == [call(1), call(3)]

    @pytest.mark.unit
    def test_release_all_for_worker_removes_matching_end_to_end(self, sqlite_app_db: AppDb) -> None:
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
            model_path="/models/b.onnx",
            promised_mb=256.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )
        sqlite_app_db.promise_vram(
            worker_id="worker:2",
            pid=3,
            model_path="/models/c.onnx",
            promised_mb=128.0,
            total_mb=8000.0,
            used_mb=1000.0,
        )
        sqlite_app_db.release_all_for_worker(worker_id="worker:1")

        remaining = sqlite_app_db.list_vram_promises()
        assert len(remaining) == 1
        assert remaining[0]["worker_id"] == "worker:2"


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Worker Restart Policy Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbWorkerRestartPolicyMethods:
    @pytest.mark.unit
    def test_get_worker_restart_policy_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected = {"max_retries": 3}
        mock_app_repo.get_worker_restart_policy.return_value = expected

        result = app_db.get_worker_restart_policy("ml-worker")

        assert result == expected
        mock_app_repo.get_worker_restart_policy.assert_called_once_with("ml-worker")

    @pytest.mark.unit
    def test_get_worker_restart_policy_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_worker_restart_policy.return_value = None

        result = app_db.get_worker_restart_policy("unknown")

        assert result is None

    @pytest.mark.unit
    def test_update_worker_restart_policy_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        fields = {"max_retries": 5}

        app_db.update_worker_restart_policy("ml-worker", fields)

        mock_app_repo.upsert_worker_restart_policy.assert_called_once_with("ml-worker", fields)

    @pytest.mark.unit
    def test_upsert_worker_restart_policy_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        fields = {"max_retries": 5}

        app_db.upsert_worker_restart_policy("ml-worker", fields)

        mock_app_repo.upsert_worker_restart_policy.assert_called_once_with("ml-worker", fields)


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Session Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbSessionMethods:
    @pytest.mark.unit
    def test_insert_session_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        payloads = [{"id": "s1", "data": {}, "expires_at": 9999}]

        app_db.insert_session(payloads)

        mock_app_repo.insert_session.assert_called_once_with(payloads)

    @pytest.mark.unit
    def test_delete_session_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.delete_session("s1")

        mock_app_repo.delete_session.assert_called_once_with("s1")

    @pytest.mark.unit
    def test_get_sessions_expiring_before_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected: list[SessionRow] = [{"id": "s1", "data": {}, "expires_at": 100}]
        mock_app_repo.get_sessions_expiring_before.return_value = expected

        result = app_db.get_sessions_expiring_before(500, 10)

        assert result == expected
        mock_app_repo.get_sessions_expiring_before.assert_called_once_with(500, 10)

    @pytest.mark.unit
    def test_count_sessions_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.count_sessions.return_value = 5

        result = app_db.count_sessions()

        assert result == 5
        mock_app_repo.count_sessions.assert_called_once_with()

    @pytest.mark.unit
    def test_delete_sessions_by_ids_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.delete_sessions_by_ids(["s1", "s2"])

        mock_app_repo.delete_sessions_by_ids.assert_called_once_with(["s1", "s2"])

    @pytest.mark.unit
    def test_get_active_sessions_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected: list[SessionRow] = []
        mock_app_repo.get_active_sessions.return_value = expected

        result = app_db.get_active_sessions(1000, 50)

        assert result == expected
        mock_app_repo.get_active_sessions.assert_called_once_with(1000, 50)


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Config/Meta Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbConfigMetaMethods:
    @pytest.mark.unit
    def test_get_config_option_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        expected: ConfigOption = ConfigOption(key="config_scan_interval", value={"interval": 300})
        mock_app_repo.get_meta.return_value = {"key": "config_scan_interval", "value": {"interval": 300}}

        result = app_db.get_config_option("config_scan_interval")

        assert result == expected
        mock_app_repo.get_meta.assert_called_once_with("config_scan_interval")

    @pytest.mark.unit
    def test_get_config_option_returns_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_meta.return_value = None

        result = app_db.get_config_option("missing_key")

        assert result is None

    @pytest.mark.unit
    def test_get_schema_version_returns_string_value(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_meta.return_value = {"key": "version", "value": "2.5.0"}

        result = app_db.get_schema_version()

        assert result == "2.5.0"
        mock_app_repo.get_meta.assert_called_once_with("version")

    @pytest.mark.unit
    def test_get_schema_version_returns_none_when_no_row(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_meta.return_value = None

        result = app_db.get_schema_version()

        assert result is None

    @pytest.mark.unit
    def test_get_schema_version_returns_none_when_value_is_none(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_meta.return_value = {"key": "version", "value": None}

        result = app_db.get_schema_version()

        assert result is None

    @pytest.mark.unit
    def test_get_schema_version_coerces_int_to_str(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.get_meta.return_value = {"key": "version", "value": 42}

        result = app_db.get_schema_version()

        assert result == "42"

    @pytest.mark.unit
    def test_list_config_options_loads_documents_for_keys(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.list_meta_keys_by_prefix.return_value = ["config_a", "config_b"]
        mock_app_repo.get_meta.side_effect = [
            {"key": "config_a", "value": 1},
            {"key": "config_b", "value": 2},
        ]

        result = app_db.list_config_options("config_")

        assert result == [
            ConfigOption(key="config_a", value=1),
            ConfigOption(key="config_b", value=2),
        ]
        mock_app_repo.list_meta_keys_by_prefix.assert_called_once_with("config_")
        assert mock_app_repo.get_meta.call_args_list == [call("config_a"), call("config_b")]

    @pytest.mark.unit
    def test_list_config_options_skips_none_rows(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.list_meta_keys_by_prefix.return_value = ["config_a", "config_b"]
        mock_app_repo.get_meta.side_effect = [
            {"key": "config_a", "value": 1},
            None,
        ]

        result = app_db.list_config_options("config_")

        assert result == [ConfigOption(key="config_a", value=1)]

    @pytest.mark.unit
    def test_list_config_options_no_prefix_passes_empty_string(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        mock_app_repo.list_meta_keys_by_prefix.return_value = []

        app_db.list_config_options()

        mock_app_repo.list_meta_keys_by_prefix.assert_called_once_with("")

    @pytest.mark.unit
    def test_update_config_option_delegates_to_upsert_meta(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        payload = {"value": 600}

        app_db.update_config_option("config_scan_interval", payload)

        mock_app_repo.upsert_meta.assert_called_once_with("config_scan_interval", payload)

    @pytest.mark.unit
    def test_remove_config_option_delegates_to_delete_meta(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.remove_config_option("config_a")

        mock_app_repo.delete_meta.assert_called_once_with("config_a")


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Cleanup/Shim Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbCleanupShimMethods:
    @pytest.mark.unit
    def test_remove_pipeline_state_deletes_rows(self, app_db: AppDb, mock_pipeline_repo: MagicMock) -> None:
        app_db.remove_pipeline_state(5)

        mock_pipeline_repo.delete_pipeline_state.assert_called_once_with(5)


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Surface Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbSurface:
    @pytest.mark.unit
    def test_exposes_maintenance_surface(self, app_db: AppDb) -> None:
        assert hasattr(app_db, "truncate_worker_claims")
        assert hasattr(app_db, "truncate_health")
        assert hasattr(app_db, "truncate_song_state_edges")

    @pytest.mark.unit
    def test_maintenance_methods_not_on_app_db(self, app_db: AppDb) -> None:
        assert not hasattr(app_db, "get_state_edges_for_files")
        assert not hasattr(app_db, "count_pipeline_states")
        assert not hasattr(app_db, "claim_file")
        assert not hasattr(app_db, "steal_claim")
        assert not hasattr(app_db, "list_libraries_in_pipeline_state")
        assert not hasattr(app_db, "count_calibration_states")


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
        app_db.truncate_worker_claims()

        mock_app_repo.truncate_worker_claims.assert_called_once_with()

    @pytest.mark.unit
    def test_truncate_health_delegates(self, app_db: AppDb, mock_app_repo: MagicMock) -> None:
        app_db.truncate_health()

        mock_app_repo.truncate_health.assert_called_once_with()
