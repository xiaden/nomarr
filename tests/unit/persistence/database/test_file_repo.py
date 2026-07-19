"""Unit tests for FileRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, insert

from nomarr.persistence.database.file_repo import FileRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile


def _create_library(session) -> int:
    """Helper: insert a library row and return its id."""
    r = session.execute(
        insert(Library).values(
            name="File Lib",
            path="/file/lib",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    return r.inserted_primary_key[0]


def _create_file(session, library_id: int, path: str = "/music/test.mp3") -> int:
    """Helper: insert a file row and return its id."""
    r = session.execute(
        insert(LibraryFile).values(
            library_id=library_id,
            folder_id=None,
            path=path,
            normalized_path=path,
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
    return r.inserted_primary_key[0]


@pytest.mark.unit
@pytest.mark.integration
class TestFileRepository:
    """Tests for FileRepository CRUD and query methods."""

    # ── basic CRUD ──────────────────────────────────────────────

    def test_add_file_returns_id(self, pg_session) -> None:
        """add_file should insert a row and return its id."""
        lib_id = _create_library(pg_session)
        repo = FileRepository(pg_session)
        file_id = repo.add_file(
            {
                "library_id": lib_id,
                "folder_id": None,
                "path": "/music/test.mp3",
                "normalized_path": "/music/test.mp3",
                "file_size": 1024,
                "modified_time": 1000,
                "duration_seconds": 180,
                "chromaprint": None,
                "needs_tagging": 1,
                "is_valid": 1,
                "tagged": 0,
                "calibration_hash": None,
                "write_claimed_by": None,
                "last_tagged_at": None,
                "scanned_at": 1000,
                "created_at": 1000,
            }
        )
        assert isinstance(file_id, int)
        assert file_id > 0

    def test_get_file_existing(self, pg_session) -> None:
        """get_file should return the file as a dict."""
        lib_id = _create_library(pg_session)
        file_id = _create_file(pg_session, lib_id)
        repo = FileRepository(pg_session)
        result = repo.get_file(file_id)
        assert result is not None
        assert result["id"] == file_id
        assert result["path"] == "/music/test.mp3"

    def test_get_file_nonexistent(self, pg_session) -> None:
        """get_file should return None for missing id."""
        repo = FileRepository(pg_session)
        result = repo.get_file(999999)
        assert result is None

    def test_get_file_by_path(self, pg_session) -> None:
        """get_file_by_path should find file by path and library_id."""
        lib_id = _create_library(pg_session)
        _create_file(pg_session, lib_id, "/music/unique.mp3")
        repo = FileRepository(pg_session)
        result = repo.get_file_by_path("/music/unique.mp3", lib_id)
        assert result is not None
        assert result["path"] == "/music/unique.mp3"
        assert result["library_id"] == lib_id

    def test_get_file_by_path_nonexistent(self, pg_session) -> None:
        """get_file_by_path should return None for missing path."""
        repo = FileRepository(pg_session)
        result = repo.get_file_by_path("/does/not/exist.mp3", 999)
        assert result is None

    def test_get_file_by_path_unscoped(self, pg_session) -> None:
        """get_file_by_path_unscoped should find file across all libraries."""
        lib_id = _create_library(pg_session)
        _create_file(pg_session, lib_id, "/music/global.mp3")
        repo = FileRepository(pg_session)
        result = repo.get_file_by_path_unscoped("/music/global.mp3")
        assert result is not None
        assert result["path"] == "/music/global.mp3"

    def test_get_file_by_normalized_path(self, pg_session) -> None:
        """get_file_by_normalized_path should find file by normalized path."""
        lib_id = _create_library(pg_session)
        _create_file(pg_session, lib_id, "/music/normal.mp3")
        repo = FileRepository(pg_session)
        result = repo.get_file_by_normalized_path(lib_id, "/music/normal.mp3")
        assert result is not None
        assert result["normalized_path"] == "/music/normal.mp3"

    def test_upsert_file_insert(self, pg_session) -> None:
        """upsert_file should insert if not exists."""
        lib_id = _create_library(pg_session)
        repo = FileRepository(pg_session)
        file_id = repo.upsert_file(
            {
                "library_id": lib_id,
                "folder_id": None,
                "path": "/music/upsert1.mp3",
                "normalized_path": "/music/upsert1.mp3",
                "file_size": 1024,
                "modified_time": 1000,
                "duration_seconds": 180,
                "chromaprint": None,
                "needs_tagging": 1,
                "is_valid": 1,
                "tagged": 0,
                "calibration_hash": None,
                "write_claimed_by": None,
                "last_tagged_at": None,
                "scanned_at": 1000,
                "created_at": 1000,
            }
        )
        assert isinstance(file_id, int)
        assert file_id > 0

    def test_upsert_file_update(self, pg_session) -> None:
        """upsert_file should update if exists."""
        lib_id = _create_library(pg_session)
        repo = FileRepository(pg_session)
        repo.upsert_file(
            {
                "library_id": lib_id,
                "folder_id": None,
                "path": "/music/upsert2.mp3",
                "normalized_path": "/music/upsert2.mp3",
                "file_size": 1024,
                "modified_time": 1000,
                "duration_seconds": 180,
                "chromaprint": None,
                "needs_tagging": 1,
                "is_valid": 1,
                "tagged": 0,
                "calibration_hash": None,
                "write_claimed_by": None,
                "last_tagged_at": None,
                "scanned_at": 1000,
                "created_at": 1000,
            }
        )
        repo.upsert_file(
            {
                "library_id": lib_id,
                "folder_id": None,
                "path": "/music/upsert2.mp3",
                "normalized_path": "/music/upsert2.mp3",
                "file_size": 2048,
                "modified_time": 2000,
                "duration_seconds": 180,
                "chromaprint": None,
                "needs_tagging": 1,
                "is_valid": 1,
                "tagged": 0,
                "calibration_hash": None,
                "write_claimed_by": None,
                "last_tagged_at": None,
                "scanned_at": 1000,
                "created_at": 1000,
            }
        )
        result = repo.get_file_by_path("/music/upsert2.mp3", lib_id)
        assert result is not None
        assert result["file_size"] == 2048

    def test_upsert_files_for_library(self, pg_session) -> None:
        """upsert_files_for_library should batch upsert files."""
        lib_id = _create_library(pg_session)
        repo = FileRepository(pg_session)
        payloads = [
            {
                "path": "/music/batch1.mp3",
                "normalized_path": "/music/batch1.mp3",
                "file_size": 1024,
                "modified_time": 1000,
                "duration_seconds": 180,
                "needs_tagging": 1,
                "is_valid": 1,
                "tagged": 0,
                "scanned_at": 1000,
                "created_at": 1000,
            },
            {
                "path": "/music/batch2.mp3",
                "normalized_path": "/music/batch2.mp3",
                "file_size": 2048,
                "modified_time": 1000,
                "duration_seconds": 180,
                "needs_tagging": 1,
                "is_valid": 1,
                "tagged": 0,
                "scanned_at": 1000,
                "created_at": 1000,
            },
        ]
        ids = repo.upsert_files_for_library(lib_id, payloads)
        assert len(ids) == 2
        assert all(isinstance(i, int) for i in ids)

    def test_update_file(self, pg_session) -> None:
        """update_file should modify specified fields."""
        lib_id = _create_library(pg_session)
        file_id = _create_file(pg_session, lib_id)
        repo = FileRepository(pg_session)
        repo.update_file(file_id, {"file_size": 2048, "tagged": 1})
        result = repo.get_file(file_id)
        assert result is not None
        assert result["file_size"] == 2048
        assert result["tagged"] == 1

    def test_delete_file(self, pg_session) -> None:
        """delete_file should remove the row."""
        lib_id = _create_library(pg_session)
        file_id = _create_file(pg_session, lib_id)
        repo = FileRepository(pg_session)
        repo.delete_file(file_id)
        result = repo.get_file(file_id)
        assert result is None

    # ── filtered queries ────────────────────────────────────────

    def test_list_files_all(self, pg_session) -> None:
        """list_files should return all files when no filters."""
        lib_id = _create_library(pg_session)
        _create_file(pg_session, lib_id, "/music/file1.mp3")
        _create_file(pg_session, lib_id, "/music/file2.mp3")
        repo = FileRepository(pg_session)
        result = repo.list_files()
        assert len(result) >= 2

    def test_list_files_with_filters(self, pg_session) -> None:
        """list_files should filter by field equality."""
        lib_id = _create_library(pg_session)
        repo = FileRepository(pg_session)
        _create_file(pg_session, lib_id, "/music/tagged.mp3")
        repo.update_file(
            repo.add_file(
                {
                    "library_id": lib_id,
                    "folder_id": None,
                    "path": "/music/untagged.mp3",
                    "normalized_path": "/music/untagged.mp3",
                    "file_size": 1024,
                    "modified_time": 1000,
                    "duration_seconds": 180,
                    "chromaprint": None,
                    "needs_tagging": 1,
                    "is_valid": 1,
                    "tagged": 0,
                    "calibration_hash": None,
                    "write_claimed_by": None,
                    "last_tagged_at": None,
                    "scanned_at": 1000,
                    "created_at": 1000,
                }
            ),
            {"tagged": 0},
        )
        result = repo.list_files(filters={"tagged": 0})
        assert all(f["tagged"] == 0 for f in result)

    def test_list_files_with_limit(self, pg_session) -> None:
        """list_files should respect limit parameter."""
        lib_id = _create_library(pg_session)
        for i in range(5):
            _create_file(pg_session, lib_id, f"/music/limit{i}.mp3")
        repo = FileRepository(pg_session)
        result = repo.list_files(limit=3)
        assert len(result) == 3

    def test_count_files(self, pg_session) -> None:
        """count_files should return total count."""
        lib_id = _create_library(pg_session)
        _create_file(pg_session, lib_id, "/music/count1.mp3")
        _create_file(pg_session, lib_id, "/music/count2.mp3")
        repo = FileRepository(pg_session)
        result = repo.count_files()
        assert result >= 2

    def test_get_files_by_ids(self, pg_session) -> None:
        """get_files_by_ids should return files for given ids."""
        lib_id = _create_library(pg_session)
        id1 = _create_file(pg_session, lib_id, "/music/batch1.mp3")
        id2 = _create_file(pg_session, lib_id, "/music/batch2.mp3")
        repo = FileRepository(pg_session)
        result = repo.get_files_by_ids([id1, id2])
        assert len(result) == 2
        ids = {f["id"] for f in result}
        assert id1 in ids
        assert id2 in ids

    def test_get_library_ids_for_files(self, pg_session) -> None:
        """get_library_ids_for_files should return {file_id: library_id}."""
        lib_id = _create_library(pg_session)
        id1 = _create_file(pg_session, lib_id, "/music/map1.mp3")
        id2 = _create_file(pg_session, lib_id, "/music/map2.mp3")
        repo = FileRepository(pg_session)
        result = repo.get_library_ids_for_files([id1, id2])
        assert result == {id1: lib_id, id2: lib_id}

    def test_list_library_file_ids(self, pg_session) -> None:
        """list_library_file_ids should return file ids for a library."""
        lib_id = _create_library(pg_session)
        _create_file(pg_session, lib_id, "/music/lib1.mp3")
        _create_file(pg_session, lib_id, "/music/lib2.mp3")
        repo = FileRepository(pg_session)
        result = repo.list_library_file_ids(lib_id)
        assert len(result) >= 2

    def test_list_library_files(self, pg_session) -> None:
        """list_library_files should return full file rows for a library."""
        lib_id = _create_library(pg_session)
        _create_file(pg_session, lib_id, "/music/full1.mp3")
        _create_file(pg_session, lib_id, "/music/full2.mp3")
        repo = FileRepository(pg_session)
        result = repo.list_library_files(lib_id)
        assert len(result) >= 2
        assert all(f["library_id"] == lib_id for f in result)

    def test_list_existing_file_paths(self, pg_session) -> None:
        """list_existing_file_paths should return paths that exist."""
        lib_id = _create_library(pg_session)
        _create_file(pg_session, lib_id, "/music/existing.mp3")
        repo = FileRepository(pg_session)
        result = repo.list_existing_file_paths(
            [
                "/music/existing.mp3",
                "/music/nonexistent.mp3",
            ]
        )
        assert "/music/existing.mp3" in result
        assert "/music/nonexistent.mp3" not in result

    def test_find_by_chromaprint(self, pg_session) -> None:
        """find_by_chromaprint should find file by chromaprint."""
        lib_id = _create_library(pg_session)
        file_id = _create_file(pg_session, lib_id, "/music/chroma.mp3")
        repo = FileRepository(pg_session)
        repo.update_file(file_id, {"chromaprint": "abc123"})
        result = repo.find_by_chromaprint(lib_id, "abc123")
        assert result is not None
        assert result["chromaprint"] == "abc123"

    def test_list_files_for_folder(self, pg_session) -> None:
        """list_files_for_folder should return files in a folder."""
        lib_id = _create_library(pg_session)
        _create_file(pg_session, lib_id, "/music/folder/file1.mp3")
        _create_file(pg_session, lib_id, "/music/folder/file2.mp3")
        _create_file(pg_session, lib_id, "/music/other/file3.mp3")
        repo = FileRepository(pg_session)
        result = repo.list_files_for_folder(lib_id, "/music/folder")
        assert len(result) == 2
        assert all(f["path"].startswith("/music/folder/") for f in result)

    # ── mutation / maintenance ──────────────────────────────────

    def test_remove_files(self, pg_session) -> None:
        """remove_files should delete multiple files."""
        lib_id = _create_library(pg_session)
        id1 = _create_file(pg_session, lib_id, "/music/remove1.mp3")
        id2 = _create_file(pg_session, lib_id, "/music/remove2.mp3")
        repo = FileRepository(pg_session)
        repo.remove_files([id1, id2])
        result = repo.get_files_by_ids([id1, id2])
        assert len(result) == 0

    def test_list_orphaned_file_ids(self, pg_session) -> None:
        """list_orphaned_file_ids should return files with missing library."""
        from sqlalchemy import text

        # Create library and file
        lib_id = _create_library(pg_session)
        file_id = _create_file(pg_session, lib_id, "/music/orphan.mp3")
        # Delete the library to create an orphan — temporarily disable FK checks
        # so SQLite doesn't cascade-delete the file (library_files.library_id
        # has ondelete=CASCADE).  PostgreSQL uses ``SET session_replication_role``;
        # SQLite uses ``PRAGMA foreign_keys``.
        pg_session.execute(text("PRAGMA foreign_keys = OFF"))
        pg_session.execute(delete(Library).where(Library.id == lib_id))
        pg_session.execute(text("PRAGMA foreign_keys = ON"))
        pg_session.commit()
        repo = FileRepository(pg_session)
        result = repo.list_orphaned_file_ids()
        # Should find the orphaned file
        assert file_id in result

    def test_truncate_files(self, pg_session) -> None:
        """truncate_files should remove all file rows."""
        lib_id = _create_library(pg_session)
        _create_file(pg_session, lib_id, "/music/truncate.mp3")
        repo = FileRepository(pg_session)
        repo.truncate_files()
        result = repo.count_files()
        assert result == 0

    def test_truncate_file_links(self, pg_session) -> None:
        """truncate_file_links should remove all file_tag rows."""
        from sqlalchemy import select

        from nomarr.persistence.models.file_tag import FileTag
        from nomarr.persistence.models.tag import Tag

        lib_id = _create_library(pg_session)
        file_id = _create_file(pg_session, lib_id)
        # Create a tag first
        tag_result = pg_session.execute(
            insert(Tag).values(
                name="test_tag",
                value="test_value",
                namespace="test_ns",
                parent_tag_id=None,
                source="ml",
                confidence=0.9,
                tier=1,
                created_at=1000,
            )
        )
        tag_id = tag_result.inserted_primary_key[0]
        # Insert a file_tag
        pg_session.execute(
            insert(FileTag).values(
                file_id=file_id,
                tag_id=tag_id,
                confidence=0.9,
                source="ml",
                created_at=1000,
            )
        )
        pg_session.commit()
        repo = FileRepository(pg_session)
        repo.truncate_file_links()
        result = pg_session.execute(select(FileTag))
        assert len(result.all()) == 0
