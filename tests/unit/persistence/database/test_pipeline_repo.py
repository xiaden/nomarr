"""Unit tests for PipelineRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from nomarr.persistence.database.pipeline_repo import PipelineRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.song import Song


def _create_library(session) -> int:
    """Helper: insert a library row and return its id."""
    r = session.execute(
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


def _create_library_and_song(session) -> tuple[int, int]:
    """Helper: insert a library and song, return (library_id, song_id)."""
    lib_id = _create_library(session)
    r = session.execute(
        insert(Song).values(
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
    song_id = r.inserted_primary_key[0]
    return lib_id, song_id


@pytest.mark.unit
@pytest.mark.integration
class TestPipelineRepository:
    """Tests for PipelineRepository CRUD and query methods."""

    def test_upsert_pipeline_state_insert(self, pg_session) -> None:
        """upsert_pipeline_state should insert if not exists."""
        lib_id = _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        result = repo.get_state(lib_id, "scan_state")
        assert result is not None
        assert result["library_id"] == lib_id
        assert result["state_key"] == "scan_state"
        assert result["state_data"]["status"] == "idle"

    def test_upsert_pipeline_state_update(self, pg_session) -> None:
        """upsert_pipeline_state should update if exists."""
        lib_id = _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "running"})
        result = repo.get_state(lib_id, "scan_state")
        assert result is not None
        assert result["state_data"]["status"] == "running"

    def test_get_state_existing(self, pg_session) -> None:
        """get_state should return the pipeline state."""
        lib_id = _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        repo.upsert_pipeline_state(lib_id, "ml_state", {"status": "ready"})
        result = repo.get_state(lib_id, "ml_state")
        assert result is not None
        assert result["state_key"] == "ml_state"

    def test_get_state_nonexistent(self, pg_session) -> None:
        """get_state should return None for missing state."""
        repo = PipelineRepository(pg_session)
        result = repo.get_state(999, "nonexistent")
        assert result is None

    def test_update_pipeline_state(self, pg_session) -> None:
        """update_pipeline_state should modify state_data."""
        lib_id = _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        repo.update_pipeline_state(lib_id, "scan_state", {"status": "completed"})
        result = repo.get_state(lib_id, "scan_state")
        assert result is not None
        assert result["state_data"]["status"] == "completed"

    def test_delete_pipeline_state(self, pg_session) -> None:
        """delete_pipeline_state should remove all states for a library."""
        lib_id = _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        repo.upsert_pipeline_state(lib_id, "ml_state", {"status": "ready"})
        deleted = repo.delete_pipeline_state(lib_id)
        assert deleted == 2
        result = repo.get_state(lib_id, "scan_state")
        assert result is None

    def test_list_libraries_in_pipeline_state(self, pg_session) -> None:
        """list_libraries_in_pipeline_state should return library ids."""
        lib_id1 = _create_library(pg_session)
        lib_id2 = _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        repo.upsert_pipeline_state(lib_id1, "scan_state", {"state": "idle"})
        repo.upsert_pipeline_state(lib_id2, "scan_state", {"state": "running"})
        repo.upsert_pipeline_state(lib_id1, "ml_state", {"state": "idle"})
        result = repo.list_libraries_in_pipeline_state("scan_state", "idle")
        assert lib_id1 in result
        assert lib_id2 not in result

    def test_list_libraries_in_pipeline_state_includes_default(self, pg_session) -> None:
        """Libraries without a row should match their default pipeline state."""
        lib_id = _create_library(pg_session)
        repo = PipelineRepository(pg_session)

        result = repo.list_libraries_in_pipeline_state("scan_state", "not_scanned")

        assert lib_id in result

    def test_count_pipeline_states(self, pg_session) -> None:
        """count_pipeline_states should return total count."""
        lib_id = _create_library(pg_session)
        repo = PipelineRepository(pg_session)
        repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        repo.upsert_pipeline_state(lib_id, "ml_state", {"status": "ready"})
        result = repo.count_pipeline_states()
        assert result >= 2

    def test_list_song_docs_in_state(self, pg_session) -> None:
        """list_song_docs_in_state should return songs in a given state."""
        from nomarr.helpers.constants.file_states import STATE_PROCESSED
        from nomarr.persistence.database.song_state_repo import SongStateRepository

        _lib_id, song_id = _create_library_and_song(pg_session)
        fs_repo = SongStateRepository(pg_session)
        # Bootstrap canonical states
        fs_repo.bootstrap_states([])
        # Assign a 16-vertex state to the song
        fs_repo.assign_state(song_id, STATE_PROCESSED)

        repo = PipelineRepository(pg_session)
        result = repo.list_song_docs_in_state(STATE_PROCESSED)
        assert len(result) >= 1
        assert any(s["id"] == song_id for s in result)

    def test_get_state_edges_for_songs(self, pg_session) -> None:
        """get_state_edges_for_songs should return pipeline states for song libraries."""
        lib_id, song_id = _create_library_and_song(pg_session)
        repo = PipelineRepository(pg_session)
        repo.upsert_pipeline_state(lib_id, "scan_state", {"status": "idle"})
        result = repo.get_state_edges_for_songs([song_id])
        assert len(result) >= 1
        assert any(s["library_id"] == lib_id for s in result)

    def test_get_state_edges_for_songs_empty(self, pg_session) -> None:
        """get_state_edges_for_songs should return [] for empty song_ids."""
        repo = PipelineRepository(pg_session)
        result = repo.get_state_edges_for_songs([])
        assert result == []
