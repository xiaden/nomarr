"""Unit tests for FolderRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from nomarr.persistence.database.folder_repo import FolderRepository
from nomarr.persistence.models.library import Library


def _create_library(session) -> int:
    """Helper: insert a library row and return its id."""
    r = session.execute(
        insert(Library).values(
            name="Folder Lib",
            path="/folder/lib",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    return r.inserted_primary_key[0]


@pytest.mark.unit
@pytest.mark.integration
class TestFolderRepository:
    """Tests for FolderRepository CRUD and hierarchy query methods."""

    def test_add_folder_returns_id(self, pg_session) -> None:
        """add_folder should insert a row and return its id."""
        lib_id = _create_library(pg_session)
        repo = FolderRepository(pg_session)
        folder_id = repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": None,
                "path": "/music/root",
                "name": "root",
            }
        )
        assert isinstance(folder_id, int)
        assert folder_id > 0

    def test_add_library_folder(self, pg_session) -> None:
        """add_library_folder should create a folder linked to a library."""
        lib_id = _create_library(pg_session)
        repo = FolderRepository(pg_session)
        folder_id = repo.add_library_folder(
            lib_id,
            {
                "parent_id": None,
                "path": "/music/library1",
                "name": "library1",
                "mtime": 123,
                "file_count": 7,
                "last_scanned_at": 456,
            },
        )
        assert isinstance(folder_id, int)
        assert folder_id > 0
        result = repo.get_folder(folder_id)
        assert result is not None
        assert result["library_id"] == lib_id
        assert result["path"] == "/music/library1"
        assert result["mtime"] == 123
        assert result["file_count"] == 7
        assert result["last_scanned_at"] == 456

    def test_get_folder_existing(self, pg_session) -> None:
        """get_folder should return the folder as a dict."""
        lib_id = _create_library(pg_session)
        repo = FolderRepository(pg_session)
        folder_id = repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": None,
                "path": "/music/test",
                "name": "test",
            }
        )
        result = repo.get_folder(folder_id)
        assert result is not None
        assert result["id"] == folder_id
        assert result["path"] == "/music/test"

    def test_get_folder_nonexistent(self, pg_session) -> None:
        """get_folder should return None for missing id."""
        repo = FolderRepository(pg_session)
        result = repo.get_folder(999999)
        assert result is None

    def test_get_folder_by_path(self, pg_session) -> None:
        """get_folder_by_path should find folder by library_id and path."""
        lib_id = _create_library(pg_session)
        repo = FolderRepository(pg_session)
        repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": None,
                "path": "/music/unique",
                "name": "unique",
            }
        )
        result = repo.get_folder_by_path(lib_id, "/music/unique")
        assert result is not None
        assert result["path"] == "/music/unique"
        assert result["library_id"] == lib_id

    def test_get_folder_by_path_nonexistent(self, pg_session) -> None:
        """get_folder_by_path should return None for missing path."""
        repo = FolderRepository(pg_session)
        result = repo.get_folder_by_path(999, "/does/not/exist")
        assert result is None

    def test_list_folders_for_library(self, pg_session) -> None:
        """list_folders_for_library should return all folders in a library."""
        lib_id = _create_library(pg_session)
        repo = FolderRepository(pg_session)
        repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": None,
                "path": "/music/lib1/root",
                "name": "root",
            }
        )
        repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": None,
                "path": "/music/lib1/sub",
                "name": "sub",
            }
        )
        result = repo.list_folders_for_library(lib_id)
        assert len(result) == 2
        paths = [f["path"] for f in result]
        assert "/music/lib1/root" in paths
        assert "/music/lib1/sub" in paths

    def test_get_root_folders(self, pg_session) -> None:
        """get_root_folders should return folders with parent_id=None."""
        lib_id = _create_library(pg_session)
        repo = FolderRepository(pg_session)
        root_id = repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": None,
                "path": "/music/root",
                "name": "root",
            }
        )
        repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": root_id,
                "path": "/music/root/child",
                "name": "child",
            }
        )
        result = repo.get_root_folders(lib_id)
        assert len(result) == 1
        assert result[0]["id"] == root_id
        assert result[0]["parent_id"] is None

    def test_get_by_parent(self, pg_session) -> None:
        """get_by_parent should return child folders."""
        lib_id = _create_library(pg_session)
        repo = FolderRepository(pg_session)
        parent_id = repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": None,
                "path": "/music/parent",
                "name": "parent",
            }
        )
        repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": parent_id,
                "path": "/music/parent/child1",
                "name": "child1",
            }
        )
        repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": parent_id,
                "path": "/music/parent/child2",
                "name": "child2",
            }
        )
        result = repo.get_by_parent(lib_id, parent_id)
        assert len(result) == 2
        names = [f["name"] for f in result]
        assert "child1" in names
        assert "child2" in names

    def test_remove_library_folder(self, pg_session) -> None:
        """remove_library_folder should delete the row."""
        lib_id = _create_library(pg_session)
        repo = FolderRepository(pg_session)
        folder_id = repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": None,
                "path": "/music/delete",
                "name": "delete",
            }
        )
        repo.remove_library_folder(lib_id, folder_id)
        result = repo.get_folder(folder_id)
        assert result is None

    def test_replace_library_folders(self, pg_session) -> None:
        """replace_library_folders should delete all and insert new ones."""
        lib_id = _create_library(pg_session)
        repo = FolderRepository(pg_session)
        repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": None,
                "path": "/music/old1",
                "name": "old1",
            }
        )
        repo.add_folder(
            {
                "library_id": lib_id,
                "parent_id": None,
                "path": "/music/old2",
                "name": "old2",
            }
        )
        new_folders = [
            {"parent_id": None, "path": "/music/new1", "name": "new1"},
            {"parent_id": None, "path": "/music/new2", "name": "new2"},
        ]
        repo.replace_library_folders(lib_id, new_folders)
        result = repo.list_folders_for_library(lib_id)
        assert len(result) == 2
        paths = [f["path"] for f in result]
        assert "/music/new1" in paths
        assert "/music/new2" in paths
        assert "/music/old1" not in paths
