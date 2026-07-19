"""Unit tests for LibraryRepository."""

from __future__ import annotations

import pytest

from nomarr.persistence.database.library_repo import LibraryRepository


@pytest.mark.unit
@pytest.mark.integration
class TestLibraryRepository:
    """Tests for LibraryRepository CRUD and query methods."""

    def test_add_library_returns_id(self, pg_session) -> None:
        """add_library should insert a row and return its id."""
        repo = LibraryRepository(pg_session)
        library_id = repo.add_library(
            {
                "name": "Test Library",
                "path": "/music/test",
                "library_type": "music",
                "auto_tag": 1,
                "auto_curate": 0,
                "created_at": 1000,
                "updated_at": 1000,
            }
        )
        assert isinstance(library_id, int)
        assert library_id > 0

    def test_get_library_existing(self, pg_session) -> None:
        """get_library should return the row as a LibraryRow dict."""
        repo = LibraryRepository(pg_session)
        lib_id = repo.add_library(
            {
                "name": "Get Test",
                "path": "/music/get",
                "library_type": "music",
                "auto_tag": 0,
                "auto_curate": 0,
                "created_at": 2000,
                "updated_at": 2000,
            }
        )
        result = repo.get_library(lib_id)
        assert result is not None
        assert result["id"] == lib_id
        assert result["name"] == "Get Test"
        assert result["path"] == "/music/get"
        assert result["library_type"] == "music"
        assert result["auto_tag"] == 0
        assert result["auto_curate"] == 0

    def test_get_library_nonexistent(self, pg_session) -> None:
        """get_library should return None for missing id."""
        repo = LibraryRepository(pg_session)
        result = repo.get_library(999999)
        assert result is None

    def test_get_library_by_name_existing(self, pg_session) -> None:
        """get_library_by_name should find library by name field."""
        repo = LibraryRepository(pg_session)
        repo.add_library(
            {
                "name": "Unique Name",
                "path": "/music/unique",
                "library_type": "music",
                "auto_tag": 1,
                "auto_curate": 1,
                "created_at": 3000,
                "updated_at": 3000,
            }
        )
        result = repo.get_library_by_name("Unique Name")
        assert result is not None
        assert result["name"] == "Unique Name"
        assert result["path"] == "/music/unique"

    def test_get_library_by_name_nonexistent(self, pg_session) -> None:
        """get_library_by_name should return None for missing name."""
        repo = LibraryRepository(pg_session)
        result = repo.get_library_by_name("Does Not Exist")
        assert result is None

    def test_list_libraries_all(self, pg_session) -> None:
        """list_libraries should return all libraries."""
        repo = LibraryRepository(pg_session)
        repo.add_library(
            {
                "name": "Lib1",
                "path": "/music/lib1",
                "library_type": "music",
                "auto_tag": 0,
                "auto_curate": 0,
                "created_at": 4000,
                "updated_at": 4000,
            }
        )
        repo.add_library(
            {
                "name": "Lib2",
                "path": "/music/lib2",
                "library_type": "disabled",
                "auto_tag": 0,
                "auto_curate": 0,
                "created_at": 4001,
                "updated_at": 4001,
            }
        )
        result = repo.list_libraries()
        assert len(result) >= 2
        names = [lib["name"] for lib in result]
        assert "Lib1" in names
        assert "Lib2" in names

    def test_list_libraries_enabled_only(self, pg_session) -> None:
        """list_libraries(enabled_only=True) should exclude disabled types."""
        repo = LibraryRepository(pg_session)
        repo.add_library(
            {
                "name": "Enabled Lib",
                "path": "/music/enabled",
                "library_type": "music",
                "auto_tag": 0,
                "auto_curate": 0,
                "created_at": 5000,
                "updated_at": 5000,
            }
        )
        repo.add_library(
            {
                "name": "Disabled Lib",
                "path": "/music/disabled",
                "library_type": "disabled",
                "auto_tag": 0,
                "auto_curate": 0,
                "created_at": 5001,
                "updated_at": 5001,
            }
        )
        result = repo.list_libraries(enabled_only=True)
        names = [lib["name"] for lib in result]
        assert "Enabled Lib" in names
        assert "Disabled Lib" not in names

    def test_list_library_keys(self, pg_session) -> None:
        """list_library_keys should return all library ids."""
        repo = LibraryRepository(pg_session)
        id1 = repo.add_library(
            {
                "name": "Keys1",
                "path": "/music/keys1",
                "library_type": "music",
                "auto_tag": 0,
                "auto_curate": 0,
                "created_at": 6000,
                "updated_at": 6000,
            }
        )
        id2 = repo.add_library(
            {
                "name": "Keys2",
                "path": "/music/keys2",
                "library_type": "music",
                "auto_tag": 0,
                "auto_curate": 0,
                "created_at": 6001,
                "updated_at": 6001,
            }
        )
        keys = repo.list_library_keys()
        assert id1 in keys
        assert id2 in keys

    def test_update_library(self, pg_session) -> None:
        """update_library should modify specified fields."""
        repo = LibraryRepository(pg_session)
        lib_id = repo.add_library(
            {
                "name": "Update Me",
                "path": "/music/update",
                "library_type": "music",
                "auto_tag": 0,
                "auto_curate": 0,
                "created_at": 7000,
                "updated_at": 7000,
            }
        )
        repo.update_library(lib_id, {"name": "Updated Name", "auto_tag": 1})
        result = repo.get_library(lib_id)
        assert result is not None
        assert result["name"] == "Updated Name"
        assert result["auto_tag"] == 1
        assert result["path"] == "/music/update"  # unchanged

    def test_delete_library(self, pg_session) -> None:
        """delete_library should remove the row."""
        repo = LibraryRepository(pg_session)
        lib_id = repo.add_library(
            {
                "name": "Delete Me",
                "path": "/music/delete",
                "library_type": "music",
                "auto_tag": 0,
                "auto_curate": 0,
                "created_at": 8000,
                "updated_at": 8000,
            }
        )
        repo.delete_library(lib_id)
        result = repo.get_library(lib_id)
        assert result is None

    def test_get_pipeline_state_returns_defaults(self, pg_session) -> None:
        """get_pipeline_state should return dict with defaults when columns missing."""
        repo = LibraryRepository(pg_session)
        lib_id = repo.add_library(
            {
                "name": "Pipeline Test",
                "path": "/music/pipeline",
                "library_type": "music",
                "auto_tag": 0,
                "auto_curate": 0,
                "created_at": 9000,
                "updated_at": 9000,
            }
        )
        state = repo.get_pipeline_state(lib_id)
        assert state is not None
        assert state["scan_state"] == "not_scanned"
        assert state["ml_state"] == "not_ML_processed"
        assert state["calibration_state"] == "not_calibrated"
        assert state["tag_write_state"] == "not_written"

    def test_get_pipeline_state_nonexistent(self, pg_session) -> None:
        """get_pipeline_state should return None for missing library."""
        repo = LibraryRepository(pg_session)
        state = repo.get_pipeline_state(999999)
        assert state is None

    def test_remove_library_cascades(self, pg_session) -> None:
        """remove_library should delete via ORM with cascade."""
        repo = LibraryRepository(pg_session)
        lib_id = repo.add_library(
            {
                "name": "Remove Me",
                "path": "/music/remove",
                "library_type": "music",
                "auto_tag": 0,
                "auto_curate": 0,
                "created_at": 10000,
                "updated_at": 10000,
            }
        )
        repo.remove_library(lib_id)
        result = repo.get_library(lib_id)
        assert result is None
