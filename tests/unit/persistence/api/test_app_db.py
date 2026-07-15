# mypy: disable-error-code=func-returns-value
"""Unit tests for ``AppDb``, ``AppMaintenanceDb``, and ``AppLegacyNavidromeDb`` delegation.

All three classes are thin facades over PostgreSQL repositories.  Each test
verifies that the correct repository method is called with the correct
arguments and that the return value is propagated.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, call

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from nomarr.helpers.constants.pipeline_states import PIPELINE_DEFAULTS
from nomarr.helpers.dto.navidrome_repo_dto import NdPlayRecord, NdTrackRecord
from nomarr.helpers.dto.repo_dto import (
    HealthRow,
    LibraryFileRow,
    LibraryScanRow,
    LockRow,
    MetaRow,
    SessionRow,
    WorkerClaimRow,
)
from nomarr.persistence.api.application import (
    AppDb,
    AppLegacyNavidromeDb,
    AppMaintenanceDb,
)
from nomarr.persistence.database.app_repo import AppRepository
from nomarr.persistence.database.file_state_repo import FileStateRepository
from nomarr.persistence.database.library_repo import LibraryRepository
from nomarr.persistence.database.navidrome_repo import NavidromeRepo
from nomarr.persistence.database.pipeline_repo import PipelineRepository
from nomarr.persistence.database.scan_repo import ScanRepository

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_app_repo() -> AsyncMock:
    return AsyncMock(spec=AppRepository)


@pytest.fixture
def mock_scan_repo() -> AsyncMock:
    return AsyncMock(spec=ScanRepository)


@pytest.fixture
def mock_library_repo() -> AsyncMock:
    return AsyncMock(spec=LibraryRepository)


@pytest.fixture
def mock_navidrome_repo() -> AsyncMock:
    return AsyncMock(spec=NavidromeRepo)


@pytest.fixture
def mock_file_state_repo() -> AsyncMock:
    return AsyncMock(spec=FileStateRepository)


@pytest.fixture
def mock_pipeline_repo() -> AsyncMock:
    return AsyncMock(spec=PipelineRepository)


@pytest.fixture
def app_db(
    mock_session: AsyncMock,
    mock_app_repo: AsyncMock,
    mock_scan_repo: AsyncMock,
    mock_library_repo: AsyncMock,
    mock_navidrome_repo: AsyncMock,
    mock_file_state_repo: AsyncMock,
    mock_pipeline_repo: AsyncMock,
) -> AppDb:
    return AppDb(
        session=mock_session,
        app_repo=mock_app_repo,
        scan_repo=mock_scan_repo,
        library_repo=mock_library_repo,
        navidrome_repo=mock_navidrome_repo,
        file_state_repo=mock_file_state_repo,
        pipeline_repo=mock_pipeline_repo,
    )


@pytest.fixture
def maintenance_db(
    mock_session: AsyncMock,
    mock_app_repo: AsyncMock,
    mock_scan_repo: AsyncMock,
    mock_file_state_repo: AsyncMock,
) -> AppMaintenanceDb:
    return AppMaintenanceDb(
        session=mock_session,
        app_repo=mock_app_repo,
        scan_repo=mock_scan_repo,
        file_state_repo=mock_file_state_repo,
    )


@pytest.fixture
def legacy_navidrome_db(mock_navidrome_repo: AsyncMock) -> AppLegacyNavidromeDb:
    return AppLegacyNavidromeDb(navidrome_repo=mock_navidrome_repo)


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — File State Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbFileStateMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_file_state_delegates_to_file_state_repo(
        self, app_db: AppDb, mock_file_state_repo: AsyncMock
    ) -> None:
        mock_file_state_repo.get_file_state.return_value = "queued"

        result = await app_db.get_file_state(42)

        assert result == "queued"
        mock_file_state_repo.get_file_state.assert_awaited_once_with(42)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_file_state_returns_none_when_no_state(
        self, app_db: AppDb, mock_file_state_repo: AsyncMock
    ) -> None:
        mock_file_state_repo.get_file_state.return_value = None

        result = await app_db.get_file_state(99)

        assert result is None
        mock_file_state_repo.get_file_state.assert_awaited_once_with(99)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_file_states_for_files_delegates(self, app_db: AppDb, mock_file_state_repo: AsyncMock) -> None:
        expected = {1: {"queued"}, 2: {"tagged", "queued"}}
        mock_file_state_repo.get_file_states_for_files.return_value = expected

        result = await app_db.get_file_states_for_files([1, 2])

        assert result == expected
        mock_file_state_repo.get_file_states_for_files.assert_awaited_once_with([1, 2])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_files_in_state_delegates(self, app_db: AppDb, mock_file_state_repo: AsyncMock) -> None:
        mock_file_state_repo.list_files_in_state.return_value = [10, 20, 30]

        result = await app_db.list_files_in_state("queued", limit=50)

        assert result == [10, 20, 30]
        mock_file_state_repo.list_files_in_state.assert_awaited_once_with("queued", limit=50)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_files_in_state_without_limit(self, app_db: AppDb, mock_file_state_repo: AsyncMock) -> None:
        mock_file_state_repo.list_files_in_state.return_value = [10]

        result = await app_db.list_files_in_state("tagged")

        assert result == [10]
        mock_file_state_repo.list_files_in_state.assert_awaited_once_with("tagged", limit=None)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_file_docs_in_state_delegates_to_pipeline_repo(
        self, app_db: AppDb, mock_pipeline_repo: AsyncMock
    ) -> None:
        expected: list[LibraryFileRow] = []
        mock_pipeline_repo.list_file_docs_in_state.return_value = expected

        result = await app_db.list_file_docs_in_state("queued", limit=10)

        assert result == expected
        mock_pipeline_repo.list_file_docs_in_state.assert_awaited_once_with("queued", limit=10)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_count_files_in_state_delegates(self, app_db: AppDb, mock_file_state_repo: AsyncMock) -> None:
        mock_file_state_repo.count_files_in_state.return_value = 7

        result = await app_db.count_files_in_state("queued")

        assert result == 7
        mock_file_state_repo.count_files_in_state.assert_awaited_once_with("queued")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_add_file_states_assigns_each_file(self, app_db: AppDb, mock_file_state_repo: AsyncMock) -> None:
        await app_db.add_file_states([1, 2, 3], "queued")

        assert mock_file_state_repo.assign_state.await_args_list == [
            call(1, "queued"),
            call(2, "queued"),
            call(3, "queued"),
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_add_file_states_empty_list_no_calls(self, app_db: AppDb, mock_file_state_repo: AsyncMock) -> None:
        await app_db.add_file_states([], "queued")

        mock_file_state_repo.assign_state.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_replace_file_states_removes_then_adds(self, app_db: AppDb, mock_file_state_repo: AsyncMock) -> None:
        await app_db.replace_file_states([1, 2], "processing")

        mock_file_state_repo.remove_states_for_files.assert_awaited_once_with([1, 2])
        assert mock_file_state_repo.assign_state.await_args_list == [
            call(1, "processing"),
            call(2, "processing"),
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_file_states_skips_empty_batch(self, app_db: AppDb, mock_file_state_repo: AsyncMock) -> None:
        await app_db.remove_file_states([])

        mock_file_state_repo.remove_states_for_files.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_file_states_delegates_non_empty(self, app_db: AppDb, mock_file_state_repo: AsyncMock) -> None:
        await app_db.remove_file_states([10, 20])

        mock_file_state_repo.remove_states_for_files.assert_awaited_once_with([10, 20])


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Scan Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbScanMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_scan_delegates_to_scan_repo(self, app_db: AppDb, mock_scan_repo: AsyncMock) -> None:
        expected: LibraryScanRow = {
            "id": 1,
            "library_id": 5,
            "status": "done",
            "scan_type": "full",
            "started_at": 0,
            "finished_at": 0,
            "files_found": 0,
            "files_processed": 0,
            "error": None,
        }
        mock_scan_repo.get_scan_record.return_value = expected

        result = await app_db.get_scan(5)

        assert result == expected
        mock_scan_repo.get_scan_record.assert_awaited_once_with(5)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_scan_returns_none_when_not_found(self, app_db: AppDb, mock_scan_repo: AsyncMock) -> None:
        mock_scan_repo.get_scan_record.return_value = None

        result = await app_db.get_scan(999)

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_add_scan_sets_library_id_default(self, app_db: AppDb, mock_scan_repo: AsyncMock) -> None:
        mock_scan_repo.create_scan.return_value = 1

        await app_db.add_scan(5, {"status": "running"})

        mock_scan_repo.create_scan.assert_awaited_once_with({"status": "running", "library_id": 5})

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_add_scan_does_not_overwrite_existing_library_id(
        self, app_db: AppDb, mock_scan_repo: AsyncMock
    ) -> None:
        mock_scan_repo.create_scan.return_value = 1

        await app_db.add_scan(5, {"status": "running", "library_id": 99})

        mock_scan_repo.create_scan.assert_awaited_once_with({"status": "running", "library_id": 99})

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_scan_updates_existing(self, app_db: AppDb, mock_scan_repo: AsyncMock) -> None:
        existing: LibraryScanRow = {
            "id": 42,
            "library_id": 5,
            "status": "running",
            "scan_type": "full",
            "started_at": 0,
            "finished_at": None,
            "files_found": 0,
            "files_processed": 0,
            "error": None,
        }
        mock_scan_repo.get_scan_record.return_value = existing

        await app_db.update_scan(5, {"status": "done"})

        mock_scan_repo.update_scan.assert_awaited_once_with(42, {"status": "done"})
        mock_scan_repo.create_scan.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_scan_falls_back_to_add_when_no_existing(
        self, app_db: AppDb, mock_scan_repo: AsyncMock
    ) -> None:
        mock_scan_repo.get_scan_record.return_value = None

        await app_db.update_scan(5, {"status": "queued"})

        mock_scan_repo.update_scan.assert_not_awaited()
        mock_scan_repo.create_scan.assert_awaited_once_with({"status": "queued", "library_id": 5})

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_scan_deletes_when_exists(self, app_db: AppDb, mock_scan_repo: AsyncMock) -> None:
        existing: LibraryScanRow = {
            "id": 42,
            "library_id": 5,
            "status": "done",
            "scan_type": "full",
            "started_at": 0,
            "finished_at": 0,
            "files_found": 0,
            "files_processed": 0,
            "error": None,
        }
        mock_scan_repo.get_scan_record.return_value = existing

        await app_db.remove_scan(5)

        mock_scan_repo.delete_scan_record.assert_awaited_once_with(42)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_scan_is_noop_when_not_found(self, app_db: AppDb, mock_scan_repo: AsyncMock) -> None:
        mock_scan_repo.get_scan_record.return_value = None

        await app_db.remove_scan(999)

        mock_scan_repo.delete_scan_record.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Pipeline State Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbPipelineStateMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_pipeline_state_delegates_to_library_repo(
        self, app_db: AppDb, mock_library_repo: AsyncMock
    ) -> None:
        expected = {
            "scan_state": "scanning",
            "ml_state": "not_ML_processed",
            "calibration_state": "not_calibrated",
            "tag_write_state": "not_written",
        }
        mock_library_repo.get_pipeline_state.return_value = expected

        result = await app_db.get_pipeline_state(5)

        assert result == expected
        mock_library_repo.get_pipeline_state.assert_awaited_once_with(5)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_pipeline_axis_delegates(self, app_db: AppDb, mock_library_repo: AsyncMock) -> None:
        await app_db.update_pipeline_axis(5, "scan_state", "scanning")

        mock_library_repo.update_pipeline_axis.assert_awaited_once_with(5, "scan_state", "scanning")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_libraries_in_axis_state_delegates(self, app_db: AppDb, mock_library_repo: AsyncMock) -> None:
        mock_library_repo.get_libraries_in_axis_state.return_value = [1, 3, 7]

        result = await app_db.get_libraries_in_axis_state("scan_state", "scanning")

        assert result == [1, 3, 7]
        mock_library_repo.get_libraries_in_axis_state.assert_awaited_once_with("scan_state", "scanning")


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Lock Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbLockMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_lock_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        expected: LockRow = {"key": "scan:1", "value": {"owner": "w1"}}
        mock_app_repo.get_lock.return_value = expected

        result = await app_db.get_lock("scan:1")

        assert result == expected
        mock_app_repo.get_lock.assert_awaited_once_with("scan:1")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_lock_returns_none_when_not_found(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.get_lock.return_value = None

        result = await app_db.get_lock("missing")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_add_lock_delegates_to_insert_lock(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        payload = {"resource_id": "scan:1"}
        mock_app_repo.insert_lock.return_value = "scan:1"

        result = await app_db.add_lock(payload)

        assert result == "scan:1"
        mock_app_repo.insert_lock.assert_awaited_once_with(payload)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_locks_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        expected: list[LockRow] = [{"key": "a", "value": {}}, {"key": "b", "value": {}}]
        mock_app_repo.list_locks.return_value = expected

        result = await app_db.list_locks()

        assert result == expected
        mock_app_repo.list_locks.assert_awaited_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_lock_delegates_to_release_lock(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        await app_db.remove_lock("scan:1")

        mock_app_repo.release_lock.assert_awaited_once_with("scan:1")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_upsert_lock_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        payload = {"owner": "w1"}

        await app_db.upsert_lock("scan:1", payload)

        mock_app_repo.upsert_lock.assert_awaited_once_with("scan:1", payload)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_acquire_lock_returns_true_on_success(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.acquire_lock.return_value = True

        result = await app_db.acquire_lock("scan:1", {"owner": "w1"})

        assert result is True
        mock_app_repo.acquire_lock.assert_awaited_once_with("scan:1", {"owner": "w1"})

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_acquire_lock_returns_false_on_conflict(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.acquire_lock.return_value = False

        result = await app_db.acquire_lock("scan:1", {"owner": "w1"})

        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Claim Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbClaimMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_add_claim_delegates_to_insert_worker_claim(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        payload = {"file_id": 1, "worker_id": "w1"}
        mock_app_repo.insert_worker_claim.return_value = 42

        result = await app_db.add_claim(payload)

        assert result == 42
        mock_app_repo.insert_worker_claim.assert_awaited_once_with(payload)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_claim_delegates_to_release_claim(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        await app_db.remove_claim(42)

        mock_app_repo.release_claim.assert_awaited_once_with(42)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_release_claim_is_alias_for_remove_claim(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        await app_db.release_claim(42)

        mock_app_repo.release_claim.assert_awaited_once_with(42)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_claims_combines_worker_and_file_removals(
        self, app_db: AppDb, mock_app_repo: AsyncMock
    ) -> None:
        mock_app_repo.delete_claims_for_workers.return_value = 2
        mock_app_repo.delete_claims_for_files.return_value = 3

        result = await app_db.remove_claims(worker_ids=["w1"], file_ids=[1, 2])

        assert result == 5
        mock_app_repo.delete_claims_for_workers.assert_awaited_once_with(["w1"])
        mock_app_repo.delete_claims_for_files.assert_awaited_once_with([1, 2])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_claims_worker_ids_only(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.delete_claims_for_workers.return_value = 4

        result = await app_db.remove_claims(worker_ids=["w1", "w2"])

        assert result == 4
        mock_app_repo.delete_claims_for_workers.assert_awaited_once_with(["w1", "w2"])
        mock_app_repo.delete_claims_for_files.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_claims_file_ids_only(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.delete_claims_for_files.return_value = 1

        result = await app_db.remove_claims(file_ids=[10])

        assert result == 1
        mock_app_repo.delete_claims_for_workers.assert_not_awaited()
        mock_app_repo.delete_claims_for_files.assert_awaited_once_with([10])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_claims_no_filters_returns_zero(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        result = await app_db.remove_claims()

        assert result == 0
        mock_app_repo.delete_claims_for_workers.assert_not_awaited()
        mock_app_repo.delete_claims_for_files.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_claims_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        expected: list[WorkerClaimRow] = []
        mock_app_repo.list_claims.return_value = expected

        result = await app_db.list_claims()

        assert result == expected
        mock_app_repo.list_claims.assert_awaited_once_with()


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Health Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbHealthMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_health_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        expected: HealthRow = {"id": 1, "worker_id": "ml-worker", "status": "healthy", "last_seen": 1000}
        mock_app_repo.get_health.return_value = expected

        result = await app_db.get_health("ml-worker")

        assert result == expected
        mock_app_repo.get_health.assert_awaited_once_with("ml-worker")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_health_returns_none_when_not_found(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.get_health.return_value = None

        result = await app_db.get_health("unknown")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_count_healthy_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.count_healthy.return_value = 3

        result = await app_db.count_healthy()

        assert result == 3
        mock_app_repo.count_healthy.assert_awaited_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_worker_health_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        expected: list[HealthRow] = [{"id": 1, "worker_id": "w1", "status": "healthy", "last_seen": 100}]
        mock_app_repo.list_worker_health.return_value = expected

        result = await app_db.list_worker_health()

        assert result == expected
        mock_app_repo.list_worker_health.assert_awaited_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_health_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        fields = {"status": "healthy", "heartbeat_ms": 1234}

        await app_db.update_health("ml-worker", fields)

        mock_app_repo.update_health.assert_awaited_once_with("ml-worker", fields)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_upsert_health_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        fields = {"status": "healthy"}

        await app_db.upsert_health("ml-worker", fields)

        mock_app_repo.upsert_health.assert_awaited_once_with("ml-worker", fields)


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Migration Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbMigrationMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_upsert_migration_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        await app_db.upsert_migration("001_initial", {"applied_at": 1000})

        mock_app_repo.upsert_migration.assert_awaited_once_with("001_initial", {"applied_at": 1000})

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_migrations_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        expected = [{"name": "001_initial", "applied_at": 1000}]
        mock_app_repo.list_migrations.return_value = expected

        result = await app_db.list_migrations()

        assert result == expected
        mock_app_repo.list_migrations.assert_awaited_once_with()


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — VRAM Promise Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbVramPromiseMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_add_vram_promise_delegates_to_upsert(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        payload = {"id": 1, "worker_id": "w1", "promised_mb": 512}

        await app_db.add_vram_promise(payload)

        mock_app_repo.upsert_vram_promise.assert_awaited_once_with(payload)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_vram_promises_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        expected = [{"id": 1, "worker_id": "w1"}]
        mock_app_repo.get_vram_promises.return_value = expected

        result = await app_db.list_vram_promises()

        assert result == expected
        mock_app_repo.get_vram_promises.assert_awaited_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_vram_promise_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        await app_db.remove_vram_promise(42)

        mock_app_repo.delete_vram_promise.assert_awaited_once_with(42)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_count_vram_promises_returns_length(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.get_vram_promises.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]

        result = await app_db.count_vram_promises()

        assert result == 3

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_count_vram_promises_empty(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.get_vram_promises.return_value = []

        result = await app_db.count_vram_promises()

        assert result == 0


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Worker Restart Policy Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbWorkerRestartPolicyMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_worker_restart_policy_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        expected = {"max_retries": 3}
        mock_app_repo.get_worker_restart_policy.return_value = expected

        result = await app_db.get_worker_restart_policy("ml-worker")

        assert result == expected
        mock_app_repo.get_worker_restart_policy.assert_awaited_once_with("ml-worker")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_worker_restart_policy_returns_none(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.get_worker_restart_policy.return_value = None

        result = await app_db.get_worker_restart_policy("unknown")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_worker_restart_policy_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        fields = {"max_retries": 5}

        await app_db.update_worker_restart_policy("ml-worker", fields)

        mock_app_repo.upsert_worker_restart_policy.assert_awaited_once_with("ml-worker", fields)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_upsert_worker_restart_policy_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        fields = {"max_retries": 5}

        await app_db.upsert_worker_restart_policy("ml-worker", fields)

        mock_app_repo.upsert_worker_restart_policy.assert_awaited_once_with("ml-worker", fields)


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Session Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbSessionMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_insert_session_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        payloads = [{"id": "s1", "data": {}, "expires_at": 9999}]

        await app_db.insert_session(payloads)

        mock_app_repo.insert_session.assert_awaited_once_with(payloads)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_delete_session_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        await app_db.delete_session("s1")

        mock_app_repo.delete_session.assert_awaited_once_with("s1")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_sessions_expiring_before_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        expected: list[SessionRow] = [{"id": "s1", "data": {}, "expires_at": 100}]
        mock_app_repo.get_sessions_expiring_before.return_value = expected

        result = await app_db.get_sessions_expiring_before(500, 10)

        assert result == expected
        mock_app_repo.get_sessions_expiring_before.assert_awaited_once_with(500, 10)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_count_sessions_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.count_sessions.return_value = 5

        result = await app_db.count_sessions()

        assert result == 5
        mock_app_repo.count_sessions.assert_awaited_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_delete_sessions_by_ids_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        await app_db.delete_sessions_by_ids(["s1", "s2"])

        mock_app_repo.delete_sessions_by_ids.assert_awaited_once_with(["s1", "s2"])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_active_sessions_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        expected: list[SessionRow] = []
        mock_app_repo.get_active_sessions.return_value = expected

        result = await app_db.get_active_sessions(1000, 50)

        assert result == expected
        mock_app_repo.get_active_sessions.assert_awaited_once_with(1000, 50)


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Config/Meta Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbConfigMetaMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_config_option_delegates(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        expected: MetaRow = {"key": "config_scan_interval", "value": {"interval": 300}}
        mock_app_repo.get_meta.return_value = expected

        result = await app_db.get_config_option("config_scan_interval")

        assert result == expected
        mock_app_repo.get_meta.assert_awaited_once_with("config_scan_interval")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_config_option_returns_none(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.get_meta.return_value = None

        result = await app_db.get_config_option("missing_key")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_schema_version_returns_string_value(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.get_meta.return_value = {"key": "version", "value": "2.5.0"}

        result = await app_db.get_schema_version()

        assert result == "2.5.0"
        mock_app_repo.get_meta.assert_awaited_once_with("version")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_schema_version_returns_none_when_no_row(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.get_meta.return_value = None

        result = await app_db.get_schema_version()

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_schema_version_returns_none_when_value_is_none(
        self, app_db: AppDb, mock_app_repo: AsyncMock
    ) -> None:
        mock_app_repo.get_meta.return_value = {"key": "version", "value": None}

        result = await app_db.get_schema_version()

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_schema_version_coerces_int_to_str(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.get_meta.return_value = {"key": "version", "value": 42}

        result = await app_db.get_schema_version()

        assert result == "42"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_config_options_loads_documents_for_keys(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.list_meta_keys_by_prefix.return_value = ["config_a", "config_b"]
        mock_app_repo.get_meta.side_effect = [
            {"key": "config_a", "value": 1},
            {"key": "config_b", "value": 2},
        ]

        result = await app_db.list_config_options("config_")

        assert result == [{"key": "config_a", "value": 1}, {"key": "config_b", "value": 2}]
        mock_app_repo.list_meta_keys_by_prefix.assert_awaited_once_with("config_")
        assert mock_app_repo.get_meta.await_args_list == [call("config_a"), call("config_b")]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_config_options_skips_none_rows(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        mock_app_repo.list_meta_keys_by_prefix.return_value = ["config_a", "config_b"]
        mock_app_repo.get_meta.side_effect = [
            {"key": "config_a", "value": 1},
            None,
        ]

        result = await app_db.list_config_options("config_")

        assert result == [{"key": "config_a", "value": 1}]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_config_options_no_prefix_passes_empty_string(
        self, app_db: AppDb, mock_app_repo: AsyncMock
    ) -> None:
        mock_app_repo.list_meta_keys_by_prefix.return_value = []

        await app_db.list_config_options()

        mock_app_repo.list_meta_keys_by_prefix.assert_awaited_once_with("")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_config_option_delegates_to_upsert_meta(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        payload = {"value": 600}

        await app_db.update_config_option("config_scan_interval", payload)

        mock_app_repo.upsert_meta.assert_awaited_once_with("config_scan_interval", payload)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_config_option_delegates_to_delete_meta(self, app_db: AppDb, mock_app_repo: AsyncMock) -> None:
        await app_db.remove_config_option("config_a")

        mock_app_repo.delete_meta.assert_awaited_once_with("config_a")


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Navidrome Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbNavidromeMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_upsert_navidrome_track_delegates(self, app_db: AppDb, mock_navidrome_repo: AsyncMock) -> None:
        expected: NdTrackRecord = {
            "id": "nd1",
            "title": "Song",
            "artist": "Art",
            "album": "Alb",
            "file_path": "/p",
            "created_at": 100,
        }
        mock_navidrome_repo.upsert_track.return_value = expected

        result = await app_db.upsert_navidrome_track("nd1", "Song", "Art", "Alb", "/p")

        assert result == expected
        mock_navidrome_repo.upsert_track.assert_awaited_once_with("nd1", "Song", "Art", "Alb", "/p")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_map_navidrome_track_to_file_delegates(self, app_db: AppDb, mock_navidrome_repo: AsyncMock) -> None:
        await app_db.map_navidrome_track_to_file("nd1", 42)

        mock_navidrome_repo.map_track_to_file.assert_awaited_once_with("nd1", 42)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_mapped_file_for_navidrome_track_delegates(
        self, app_db: AppDb, mock_navidrome_repo: AsyncMock
    ) -> None:
        mock_navidrome_repo.get_mapped_file.return_value = 42

        result = await app_db.get_mapped_file_for_navidrome_track("nd1")

        assert result == 42
        mock_navidrome_repo.get_mapped_file.assert_awaited_once_with("nd1")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_mapped_file_returns_none(self, app_db: AppDb, mock_navidrome_repo: AsyncMock) -> None:
        mock_navidrome_repo.get_mapped_file.return_value = None

        result = await app_db.get_mapped_file_for_navidrome_track("nd_missing")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_resolve_file_to_navidrome_track_delegates(
        self, app_db: AppDb, mock_navidrome_repo: AsyncMock
    ) -> None:
        mock_navidrome_repo.resolve_file_to_nd_track.return_value = "nd1"

        result = await app_db.resolve_file_to_navidrome_track(42)

        assert result == "nd1"
        mock_navidrome_repo.resolve_file_to_nd_track.assert_awaited_once_with(42)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_resolve_file_returns_none(self, app_db: AppDb, mock_navidrome_repo: AsyncMock) -> None:
        mock_navidrome_repo.resolve_file_to_nd_track.return_value = None

        result = await app_db.resolve_file_to_navidrome_track(999)

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_bulk_upsert_navidrome_tracks_delegates(self, app_db: AppDb, mock_navidrome_repo: AsyncMock) -> None:
        mock_navidrome_repo.bulk_upsert_tracks.return_value = 5

        result = await app_db.bulk_upsert_navidrome_tracks(["nd1", "nd2"])

        assert result == 5
        mock_navidrome_repo.bulk_upsert_tracks.assert_awaited_once_with(["nd1", "nd2"])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_bulk_map_navidrome_tracks_delegates(self, app_db: AppDb, mock_navidrome_repo: AsyncMock) -> None:
        mappings = [{"nd_id": "nd1", "file_id": "1"}]
        mock_navidrome_repo.bulk_map_tracks.return_value = 1

        result = await app_db.bulk_map_navidrome_tracks(mappings)

        assert result == 1
        mock_navidrome_repo.bulk_map_tracks.assert_awaited_once_with(mappings)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_record_navidrome_play_delegates(self, app_db: AppDb, mock_navidrome_repo: AsyncMock) -> None:
        mock_navidrome_repo.record_play.return_value = 100

        result = await app_db.record_navidrome_play("nd1", "user1", 5000, file_id=42)

        assert result == 100
        mock_navidrome_repo.record_play.assert_awaited_once_with("nd1", "user1", 5000, 42)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_record_navidrome_play_without_file_id(self, app_db: AppDb, mock_navidrome_repo: AsyncMock) -> None:
        mock_navidrome_repo.record_play.return_value = 101

        result = await app_db.record_navidrome_play("nd1", "user1", 5000)

        assert result == 101
        mock_navidrome_repo.record_play.assert_awaited_once_with("nd1", "user1", 5000, None)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_top_navidrome_plays_delegates(self, app_db: AppDb, mock_navidrome_repo: AsyncMock) -> None:
        expected: list[NdPlayRecord] = [{"nd_id": "nd1", "file_id": 1, "playcount": 10, "last_played": 5000}]
        mock_navidrome_repo.get_top_plays.return_value = expected

        result = await app_db.get_top_navidrome_plays("user1", 5)

        assert result == expected
        mock_navidrome_repo.get_top_plays.assert_awaited_once_with("user1", 5)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_delete_navidrome_tracks_for_file_delegates(
        self, app_db: AppDb, mock_navidrome_repo: AsyncMock
    ) -> None:
        mock_navidrome_repo.delete_tracks_for_file.return_value = 3

        result = await app_db.delete_navidrome_tracks_for_file(42)

        assert result == 3
        mock_navidrome_repo.delete_tracks_for_file.assert_awaited_once_with(42)


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Cleanup/Shim Methods
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbCleanupShimMethods:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_collections_delegates_to_maintenance(self, app_db: AppDb) -> None:
        result = await app_db.list_collections()

        assert result == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_clear_file_state_links_delegates_to_maintenance(
        self, app_db: AppDb, mock_file_state_repo: AsyncMock
    ) -> None:
        await app_db.clear_file_state_links()

        # Verify it went through maintenance → file_state_repo
        assert mock_file_state_repo.truncate_assignments.await_count == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_clear_pipeline_state_links_delegates_to_maintenance(self, app_db: AppDb) -> None:
        # truncate_pipeline_state_edges is a no-op, so just verify it doesn't raise
        await app_db.clear_pipeline_state_links()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_clear_scans_delegates_to_maintenance(self, app_db: AppDb, mock_scan_repo: AsyncMock) -> None:
        await app_db.clear_scans()

        assert mock_scan_repo.truncate_scans.await_count == 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_pipeline_state_raises_not_implemented(self, app_db: AppDb) -> None:
        with pytest.raises(NotImplementedError, match="deprecated"):
            await app_db.update_pipeline_state(1, "scanning")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remove_pipeline_state_resets_all_axes(self, app_db: AppDb, mock_library_repo: AsyncMock) -> None:
        await app_db.remove_pipeline_state(5)

        assert mock_library_repo.update_pipeline_axis.await_count == len(PIPELINE_DEFAULTS)
        for axis_field, default_value in PIPELINE_DEFAULTS.items():
            mock_library_repo.update_pipeline_axis.assert_any_await(5, axis_field, default_value)


# ══════════════════════════════════════════════════════════════════════════════
# AppDb — Surface Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestAppDbSurface:
    @pytest.mark.unit
    def test_exposes_maintenance_surface(self, app_db: AppDb) -> None:
        assert isinstance(app_db.maintenance, AppMaintenanceDb)
        assert hasattr(app_db.maintenance, "truncate_worker_claims")
        assert hasattr(app_db.maintenance, "truncate_health")
        assert hasattr(app_db.maintenance, "truncate_file_state_edges")
        assert hasattr(app_db.maintenance, "truncate_scan_records")

    @pytest.mark.unit
    def test_exposes_legacy_navidrome_surface(self, app_db: AppDb) -> None:
        assert isinstance(app_db.legacy_navidrome, AppLegacyNavidromeDb)
        assert hasattr(app_db.legacy_navidrome, "get_nd_track")
        assert hasattr(app_db.legacy_navidrome, "list_nd_track_keys")

    @pytest.mark.unit
    def test_does_not_expose_maintenance_methods_at_top_level(self, app_db: AppDb) -> None:
        assert not hasattr(app_db, "truncate_worker_claims")
        assert not hasattr(app_db, "delete_all_worker_claims")
        assert not hasattr(app_db, "truncate_health")
        assert not hasattr(app_db, "truncate_file_state_edges")
        assert not hasattr(app_db, "truncate_scan_records")

    @pytest.mark.unit
    def test_does_not_expose_legacy_navidrome_methods_at_top_level(self, app_db: AppDb) -> None:
        assert not hasattr(app_db, "get_nd_track")
        assert not hasattr(app_db, "list_nd_track_keys")

    @pytest.mark.unit
    def test_does_expose_routine_navidrome_methods_at_top_level(self, app_db: AppDb) -> None:
        assert hasattr(app_db, "upsert_navidrome_track")
        assert hasattr(app_db, "map_navidrome_track_to_file")
        assert hasattr(app_db, "get_mapped_file_for_navidrome_track")
        assert hasattr(app_db, "record_navidrome_play")
        assert hasattr(app_db, "delete_navidrome_tracks_for_file")

    @pytest.mark.unit
    def test_maintenance_methods_not_on_app_db(self, app_db: AppDb) -> None:
        assert not hasattr(app_db, "get_state_edges_for_files")
        assert not hasattr(app_db, "delete_scan_records_for_library")
        assert not hasattr(app_db, "count_pipeline_states")
        assert not hasattr(app_db, "claim_file")
        assert not hasattr(app_db, "steal_claim")
        assert not hasattr(app_db, "list_libraries_in_pipeline_state")
        assert not hasattr(app_db, "count_calibration_states")


# ══════════════════════════════════════════════════════════════════════════════
# AppMaintenanceDb
# ══════════════════════════════════════════════════════════════════════════════


class TestAppMaintenanceDb:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_truncate_file_state_edges_delegates(
        self, maintenance_db: AppMaintenanceDb, mock_file_state_repo: AsyncMock
    ) -> None:
        await maintenance_db.truncate_file_state_edges()

        mock_file_state_repo.truncate_assignments.assert_awaited_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_truncate_scan_records_delegates(
        self, maintenance_db: AppMaintenanceDb, mock_scan_repo: AsyncMock
    ) -> None:
        await maintenance_db.truncate_scan_records()

        mock_scan_repo.truncate_scans.assert_awaited_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_truncate_pipeline_states_is_noop(self, maintenance_db: AppMaintenanceDb) -> None:
        result = await maintenance_db.truncate_pipeline_states()

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_truncate_pipeline_state_edges_is_noop(self, maintenance_db: AppMaintenanceDb) -> None:
        result = await maintenance_db.truncate_pipeline_state_edges()

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_truncate_worker_claims_delegates(
        self, maintenance_db: AppMaintenanceDb, mock_app_repo: AsyncMock
    ) -> None:
        await maintenance_db.truncate_worker_claims()

        mock_app_repo.truncate_worker_claims.assert_awaited_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_delete_all_worker_claims_shims_to_truncate(
        self, maintenance_db: AppMaintenanceDb, mock_app_repo: AsyncMock
    ) -> None:
        await maintenance_db.delete_all_worker_claims()

        mock_app_repo.truncate_worker_claims.assert_awaited_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_truncate_health_delegates(self, maintenance_db: AppMaintenanceDb, mock_app_repo: AsyncMock) -> None:
        await maintenance_db.truncate_health()

        mock_app_repo.truncate_health.assert_awaited_once_with()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_collections_returns_empty(self, maintenance_db: AppMaintenanceDb) -> None:
        result = await maintenance_db.list_collections()

        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# AppLegacyNavidromeDb
# ══════════════════════════════════════════════════════════════════════════════


class TestAppLegacyNavidromeDb:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_nd_track_delegates_to_navidrome_repo(
        self, legacy_navidrome_db: AppLegacyNavidromeDb, mock_navidrome_repo: AsyncMock
    ) -> None:
        expected: NdTrackRecord = {
            "id": "nd1",
            "title": "Song",
            "artist": "Art",
            "album": "Alb",
            "file_path": "/p",
            "created_at": 100,
        }
        mock_navidrome_repo.get_track.return_value = expected

        result = await legacy_navidrome_db.get_nd_track("nd1")

        assert result == expected
        mock_navidrome_repo.get_track.assert_awaited_once_with("nd1")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_nd_track_returns_none(
        self, legacy_navidrome_db: AppLegacyNavidromeDb, mock_navidrome_repo: AsyncMock
    ) -> None:
        mock_navidrome_repo.get_track.return_value = None

        result = await legacy_navidrome_db.get_nd_track("missing")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_nd_track_keys_delegates(
        self, legacy_navidrome_db: AppLegacyNavidromeDb, mock_navidrome_repo: AsyncMock
    ) -> None:
        mock_navidrome_repo.list_nd_track_keys.return_value = ["nd1", "nd2", "nd3"]

        result = await legacy_navidrome_db.list_nd_track_keys()

        assert result == ["nd1", "nd2", "nd3"]
        mock_navidrome_repo.list_nd_track_keys.assert_awaited_once_with()
