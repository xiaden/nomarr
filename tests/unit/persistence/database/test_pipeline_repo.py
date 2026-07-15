"""Unit tests for PipelineRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from nomarr.persistence.database.pipeline_repo import PipelineRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile


async def _create_library(session) -> int:
    """Helper: insert a library row and return its id."""
    r = await session.execute(
        insert(Library).values(
            name="Pipeline Lib",
            path="/pipeline/lib",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    return r.inserted_primary_key[0]


async def _create_library_and_file(session) -> tuple[int, int]:
    """Helper: insert a library and file, return (library_id, file_id)."""
    lib_id = await _create_library(session)
    r = await session.execute(
        insert(LibraryFile).values(
            library_id=lib_id,
            folder_id=None,
            path="/music/test.mp3",
            normalized_path="/music/test.mp3",
            file_size=1024,
            modified_time=1000,
            duration_seconds=180,
            chromaprint=None,
            needs_tagging=1,
            is_valid=1,
            tagged=0,
            calibration_hash=None,
            write_claimed_by=None,
            last_tagged_at=None,
            scanned_at=1000,
            created_at=1000,
        )
    )
    file_id = r.inserted_primary_key[0]
    return lib_id, file_id


@pytest.mark.unit
@pytest.mark.integration
class TestPipelineRepository:
    """Tests for PipelineRepository CRUD and query methods."""

    @pytest.mark.asyncio
    async def test_upsert_pipeline_state_insert(self, pg_session) -> None:
        """upsert_pipeline_state should insert if not exists."""
        lib_id = await _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        await repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        result = await repo.get_state(lib_id, "scan_state")
        assert result is not None
        assert result["library_id"] == lib_id
        assert result["state_key"] == "scan_state"
        assert result["state_data"]["status"] == "idle"

    @pytest.mark.asyncio
    async def test_upsert_pipeline_state_update(self, pg_session) -> None:
        """upsert_pipeline_state should update if exists."""
        lib_id = await _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        await repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        await repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "running"})
        result = await repo.get_state(lib_id, "scan_state")
        assert result is not None
        assert result["state_data"]["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_state_existing(self, pg_session) -> None:
        """get_state should return the pipeline state."""
        lib_id = await _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        await repo.upsert_pipeline_state(lib_id, "ml_state", {"status": "ready"})
        result = await repo.get_state(lib_id, "ml_state")
        assert result is not None
        assert result["state_key"] == "ml_state"

    @pytest.mark.asyncio
    async def test_get_state_nonexistent(self, pg_session) -> None:
        """get_state should return None for missing state."""
        repo = PipelineRepository(pg_session)
        result = await repo.get_state(999, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_pipeline_state(self, pg_session) -> None:
        """update_pipeline_state should modify state_data."""
        lib_id = await _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        await repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        await repo.update_pipeline_state(lib_id, "scan_state", {"status": "completed"})
        result = await repo.get_state(lib_id, "scan_state")
        assert result is not None
        assert result["state_data"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_delete_pipeline_state(self, pg_session) -> None:
        """delete_pipeline_state should remove all states for a library."""
        lib_id = await _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        await repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        await repo.upsert_pipeline_state(lib_id, "ml_state", {"status": "ready"})
        deleted = await repo.delete_pipeline_state(lib_id)
        assert deleted == 2
        result = await repo.get_state(lib_id, "scan_state")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_libraries_in_pipeline_state(self, pg_session) -> None:
        """list_libraries_in_pipeline_state should return library ids."""
        lib_id1 = await _create_library(pg_session)
        lib_id2 = await _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        await repo.upsert_pipeline_state(lib_id1, "scan_state", {"state": "idle"})
        await repo.upsert_pipeline_state(lib_id2, "scan_state", {"state": "running"})
        await repo.upsert_pipeline_state(lib_id1, "ml_state", {"state": "idle"})
        result = await repo.list_libraries_in_pipeline_state("scan_state", "idle")
        assert lib_id1 in result
        assert lib_id2 not in result

    @pytest.mark.asyncio
    async def test_count_pipeline_states(self, pg_session) -> None:
        """count_pipeline_states should return total count."""
        lib_id = await _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        await repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        await repo.upsert_pipeline_state(lib_id, "ml_state", {"status": "ready"})
        result = await repo.count_pipeline_states()
        assert result >= 2

    @pytest.mark.asyncio
    async def test_list_file_docs_in_state(self, pg_session) -> None:
        """list_file_docs_in_state should return files in a given state."""
        from nomarr.persistence.database.file_state_repo import FileStateRepository

        _lib_id, file_id = await _create_library_and_file(pg_session)
        fs_repo = FileStateRepository(pg_session)
        # Bootstrap canonical states
        await fs_repo.bootstrap_states([])
        # Assign "pending" state to file (single file_id, not list)
        await fs_repo.assign_state(file_id, "pending")

        repo = PipelineRepository(pg_session)
        result = await repo.list_file_docs_in_state("pending")
        assert len(result) >= 1
        assert any(f["id"] == file_id for f in result)

    @pytest.mark.asyncio
    async def test_get_state_edges_for_files(self, pg_session) -> None:
        """get_state_edges_for_files should return pipeline states for file libraries."""
        lib_id, file_id = await _create_library_and_file(pg_session)
        repo = PipelineRepository(pg_session)
        await repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        result = await repo.get_state_edges_for_files([file_id])
        assert len(result) >= 1
        assert any(s["library_id"] == lib_id for s in result)

    @pytest.mark.asyncio
    async def test_get_state_edges_for_files_empty(self, pg_session) -> None:
        """get_state_edges_for_files should return [] for empty file_ids."""
        repo = PipelineRepository(pg_session)
        result = await repo.get_state_edges_for_files([])
        assert result == []
