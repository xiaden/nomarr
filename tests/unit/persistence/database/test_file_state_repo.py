"""Unit tests for FileStateRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, insert, select

from nomarr.persistence.database.file_state_repo import FileStateRepository
from nomarr.persistence.models.file_state import FileState
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile


async def _create_library_and_file(session) -> tuple[int, int]:
    """Helper: insert a library and file, return (library_id, file_id)."""
    lib_r = await session.execute(
        insert(Library).values(
            name="State Lib",
            path="/state/lib",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    lib_id = lib_r.inserted_primary_key[0]
    file_r = await session.execute(
        insert(LibraryFile).values(
            library_id=lib_id,
            path="/state/lib/test.mp3",
            normalized_path="/state/lib/test.mp3",
            file_size=1000,
            modified_time=1000,
            duration_seconds=180,
            needs_tagging=0,
            is_valid=1,
            tagged=0,
            created_at=1000,
        )
    )
    file_id = file_r.inserted_primary_key[0]
    return lib_id, file_id


@pytest.mark.unit
@pytest.mark.integration
class TestFileStateRepository:
    """Tests for FileStateRepository CRUD and query methods."""

    @pytest.mark.asyncio
    async def test_get_file_state_returns_name(self, pg_session) -> None:
        """get_file_state should return the state name for a file."""
        repo = FileStateRepository(pg_session)
        await repo.bootstrap_states([])
        _, file_id = await _create_library_and_file(pg_session)

        await repo.assign_state(file_id, "pending")
        state_name = await repo.get_file_state(file_id)
        assert state_name == "pending"

    @pytest.mark.asyncio
    async def test_get_file_state_nonexistent(self, pg_session) -> None:
        """get_file_state should return None for file with no state."""
        repo = FileStateRepository(pg_session)
        result = await repo.get_file_state(999999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_file_states_for_files(self, pg_session) -> None:
        """get_file_states_for_files should return dict of file_id -> state names."""
        repo = FileStateRepository(pg_session)
        await repo.bootstrap_states([])

        # Create two files
        lib_r = await pg_session.execute(
            insert(Library).values(
                name="Batch Lib",
                path="/batch/lib",
                library_type="music",
                auto_tag=0,
                auto_curate=0,
                created_at=2000,
                updated_at=2000,
            )
        )
        lib_id = lib_r.inserted_primary_key[0]
        file1_r = await pg_session.execute(
            insert(LibraryFile).values(
                library_id=lib_id,
                path="/batch/lib/test1.mp3",
                normalized_path="/batch/lib/test1.mp3",
                file_size=1000,
                modified_time=2000,
                duration_seconds=180,
                needs_tagging=0,
                is_valid=1,
                tagged=0,
                created_at=2000,
            )
        )
        file2_r = await pg_session.execute(
            insert(LibraryFile).values(
                library_id=lib_id,
                path="/batch/lib/test2.mp3",
                normalized_path="/batch/lib/test2.mp3",
                file_size=1000,
                modified_time=2000,
                duration_seconds=180,
                needs_tagging=0,
                is_valid=1,
                tagged=0,
                created_at=2000,
            )
        )
        file1_id, file2_id = file1_r.inserted_primary_key[0], file2_r.inserted_primary_key[0]

        await repo.assign_state(file1_id, "pending")
        await repo.assign_state(file2_id, "tagged")

        result = await repo.get_file_states_for_files([file1_id, file2_id])
        assert file1_id in result
        assert file2_id in result
        assert "pending" in result[file1_id]
        assert "tagged" in result[file2_id]

    @pytest.mark.asyncio
    async def test_list_files_in_state(self, pg_session) -> None:
        """list_files_in_state should return file ids assigned to a state."""
        repo = FileStateRepository(pg_session)
        await repo.bootstrap_states([])

        lib_r = await pg_session.execute(
            insert(Library).values(
                name="List Lib",
                path="/list/lib",
                library_type="music",
                auto_tag=0,
                auto_curate=0,
                created_at=3000,
                updated_at=3000,
            )
        )
        lib_id = lib_r.inserted_primary_key[0]
        file1_r = await pg_session.execute(
            insert(LibraryFile).values(
                library_id=lib_id,
                path="/list/lib/test1.mp3",
                normalized_path="/list/lib/test1.mp3",
                file_size=1000,
                modified_time=3000,
                duration_seconds=180,
                needs_tagging=0,
                is_valid=1,
                tagged=0,
                created_at=3000,
            )
        )
        file2_r = await pg_session.execute(
            insert(LibraryFile).values(
                library_id=lib_id,
                path="/list/lib/test2.mp3",
                normalized_path="/list/lib/test2.mp3",
                file_size=1000,
                modified_time=3000,
                duration_seconds=180,
                needs_tagging=0,
                is_valid=1,
                tagged=0,
                created_at=3000,
            )
        )
        file1_id, file2_id = file1_r.inserted_primary_key[0], file2_r.inserted_primary_key[0]

        await repo.assign_state(file1_id, "pending")
        await repo.assign_state(file2_id, "pending")

        result = await repo.list_files_in_state("pending")
        assert file1_id in result
        assert file2_id in result

    @pytest.mark.asyncio
    async def test_count_files_in_state(self, pg_session) -> None:
        """count_files_in_state should return count of files in a state."""
        repo = FileStateRepository(pg_session)
        await repo.bootstrap_states([])
        _, file_id = await _create_library_and_file(pg_session)

        await repo.assign_state(file_id, "pending")
        count = await repo.count_files_in_state("pending")
        assert count >= 1

    @pytest.mark.asyncio
    async def test_assign_state(self, pg_session) -> None:
        """assign_state should create a file-state assignment."""
        repo = FileStateRepository(pg_session)
        await repo.bootstrap_states([])
        _, file_id = await _create_library_and_file(pg_session)

        await repo.assign_state(file_id, "pending")
        state_name = await repo.get_file_state(file_id)
        assert state_name == "pending"

    @pytest.mark.asyncio
    async def test_assign_state_unknown_raises(self, pg_session) -> None:
        """assign_state should raise ValueError for unknown state name."""
        repo = FileStateRepository(pg_session)
        await repo.bootstrap_states([])
        _, file_id = await _create_library_and_file(pg_session)

        with pytest.raises(ValueError, match="Unknown file state"):
            await repo.assign_state(file_id, "nonexistent_state")

    @pytest.mark.asyncio
    async def test_remove_states_for_files(self, pg_session) -> None:
        """remove_states_for_files should delete assignments."""
        repo = FileStateRepository(pg_session)
        await repo.bootstrap_states([])
        _, file_id = await _create_library_and_file(pg_session)

        await repo.assign_state(file_id, "pending")
        await repo.remove_states_for_files([file_id])

        state_name = await repo.get_file_state(file_id)
        assert state_name is None

    @pytest.mark.asyncio
    async def test_bootstrap_states_creates_canonical(self, pg_session) -> None:
        """bootstrap_states should insert canonical states if table is empty."""
        repo = FileStateRepository(pg_session)
        # Clear existing states
        await pg_session.execute(delete(FileState))
        await pg_session.commit()

        await repo.bootstrap_states([])

        # Verify canonical states exist
        result = await pg_session.execute(select(FileState))
        states = result.scalars().all()
        assert len(states) >= 5
        names = {s.name for s in states}
        assert "pending" in names
        assert "tagged" in names
        assert "curated" in names
        assert "written" in names
        assert "error" in names

    @pytest.mark.asyncio
    async def test_count_for_file_and_state(self, pg_session) -> None:
        """count_for_file_and_state should return count of assignments."""
        repo = FileStateRepository(pg_session)
        await repo.bootstrap_states([])
        _, file_id = await _create_library_and_file(pg_session)

        await repo.assign_state(file_id, "pending")

        # Get state_id for "pending"
        result = await pg_session.execute(select(FileState).where(FileState.name == "pending"))
        state = result.scalar_one()
        state_id = state.id

        count = await repo.count_for_file_and_state(file_id, state_id)
        assert count == 1

    @pytest.mark.asyncio
    async def test_truncate_assignments(self, pg_session) -> None:
        """truncate_assignments should remove all assignment rows."""
        repo = FileStateRepository(pg_session)
        await repo.bootstrap_states([])
        _, file_id = await _create_library_and_file(pg_session)

        await repo.assign_state(file_id, "pending")
        await repo.truncate_assignments()

        count = await repo.count_files_in_state("pending")
        assert count == 0
