"""Unit tests for SongRepository."""

from __future__ import annotations

from itertools import count
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.exc import IntegrityError

from nomarr.helpers.exceptions import DatabaseStateError
from nomarr.persistence.database.song_repo import SongRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.song import Song

_LIBRARY_NAMES = count(1)


def _create_library(session) -> int:
    """Helper: insert a library row and return its id."""
    r = session.execute(
        insert(Library).values(
            name=f"Song Lib {next(_LIBRARY_NAMES)}",
            path="/song/lib",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    return r.inserted_primary_key[0]


def _create_song(session, library_id: int, path: str = "/music/test.mp3", normalized_path: str | None = None) -> int:
    """Helper: insert a song row and return its id."""
    r = session.execute(
        insert(Song).values(
            library_id=library_id,
            folder_id=None,
            path=path,
            normalized_path=normalized_path if normalized_path is not None else path,
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
class TestSongRepository:
    """Tests for SongRepository CRUD and query methods."""

    # ── basic CRUD ──────────────────────────────────────────────

    def test_add_song_returns_id(self, pg_session) -> None:
        """add_song should insert a row and return its id."""
        lib_id = _create_library(pg_session)
        repo = SongRepository(pg_session)
        song_id = repo.add_song(
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
        assert isinstance(song_id, int)
        assert song_id > 0

    def test_get_song_existing(self, pg_session) -> None:
        """get_song should return the song as a dict."""
        lib_id = _create_library(pg_session)
        song_id = _create_song(pg_session, lib_id)
        repo = SongRepository(pg_session)
        result = repo.get_song(song_id)
        assert result is not None
        assert result["id"] == song_id
        assert result["path"] == "/music/test.mp3"

    def test_get_song_nonexistent(self, pg_session) -> None:
        """get_song should return None for missing id."""
        repo = SongRepository(pg_session)
        result = repo.get_song(999999)
        assert result is None

    def test_get_song_by_path(self, pg_session) -> None:
        """get_song_by_path should find song by path and library_id."""
        lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/unique.mp3")
        repo = SongRepository(pg_session)
        result = repo.get_song_by_path("/music/unique.mp3", lib_id)
        assert result is not None
        assert result["path"] == "/music/unique.mp3"
        assert result["library_id"] == lib_id

    def test_get_song_by_path_nonexistent(self, pg_session) -> None:
        """get_song_by_path should return None for missing path."""
        repo = SongRepository(pg_session)
        result = repo.get_song_by_path("/does/not/exist.mp3", 999)
        assert result is None

    def test_get_song_by_path_unscoped(self, pg_session) -> None:
        """get_song_by_path_unscoped should find song across all libraries."""
        lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/global.mp3")
        repo = SongRepository(pg_session)
        result = repo.get_song_by_path_unscoped("/music/global.mp3")
        assert result is not None
        assert result["path"] == "/music/global.mp3"

    def test_get_song_by_path_unscoped_returns_none_for_duplicate_path(self, pg_session) -> None:
        """An ambiguous path must not select an arbitrary library's song."""
        first_library_id = _create_library(pg_session)
        second_library_id = _create_library(pg_session)
        _create_song(pg_session, first_library_id, "/music/duplicate.mp3")
        _create_song(pg_session, second_library_id, "/music/duplicate.mp3")
        repo = SongRepository(pg_session)

        result = repo.get_song_by_path_unscoped("/music/duplicate.mp3")

        assert result is None

    def test_get_song_by_normalized_path(self, pg_session) -> None:
        """get_song_by_normalized_path should find song by normalized path."""
        lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/normal.mp3")
        repo = SongRepository(pg_session)
        result = repo.get_song_by_normalized_path(lib_id, "/music/normal.mp3")
        assert result is not None
        assert result["normalized_path"] == "/music/normal.mp3"

    def test_upsert_song_insert(self, pg_session) -> None:
        """upsert_song should insert if not exists."""
        lib_id = _create_library(pg_session)
        repo = SongRepository(pg_session)
        song_id = repo.upsert_song(
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
        assert isinstance(song_id, int)
        assert song_id > 0

    def test_upsert_song_update(self, pg_session) -> None:
        """upsert_song should update if exists."""
        lib_id = _create_library(pg_session)
        repo = SongRepository(pg_session)
        repo.upsert_song(
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
        repo.upsert_song(
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
        result = repo.get_song_by_path("/music/upsert2.mp3", lib_id)
        assert result is not None
        assert result["file_size"] == 2048

    def test_upsert_songs_for_library(self, pg_session) -> None:
        """upsert_songs_for_library should batch upsert songs."""
        lib_id = _create_library(pg_session)
        repo = SongRepository(pg_session)
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
                "chromaprint": "later-fingerprint",
            },
        ]
        ids = repo.upsert_songs_for_library(lib_id, payloads)
        assert len(ids) == 2
        assert all(isinstance(i, int) for i in ids)
        result = repo.get_song_by_path("/music/batch2.mp3", lib_id)
        assert result is not None
        assert result["chromaprint"] == "later-fingerprint"

    def test_update_song(self, pg_session) -> None:
        """update_song should modify specified fields."""
        lib_id = _create_library(pg_session)
        song_id = _create_song(pg_session, lib_id)
        repo = SongRepository(pg_session)
        repo.update_song(song_id, {"file_size": 2048, "tagged": 1})
        result = repo.get_song(song_id)
        assert result is not None
        assert result["file_size"] == 2048
        assert result["tagged"] == 1

    def test_delete_song(self, pg_session) -> None:
        """delete_song should remove the row."""
        lib_id = _create_library(pg_session)
        song_id = _create_song(pg_session, lib_id)
        repo = SongRepository(pg_session)
        repo.delete_song(song_id)
        result = repo.get_song(song_id)
        assert result is None

    # ── filtered queries ────────────────────────────────────────

    def test_list_songs(self, pg_session) -> None:
        """list_songs should return all songs for a library."""
        lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/file1.mp3")
        _create_song(pg_session, lib_id, "/music/file2.mp3")
        repo = SongRepository(pg_session)
        result = repo.list_songs(lib_id)
        assert len(result) >= 2
        assert all(s["library_id"] == lib_id for s in result)

    def test_list_songs_scoped_to_library(self, pg_session) -> None:
        """list_songs should only return songs belonging to the library."""
        lib_id_a = _create_library(pg_session)
        lib_id_b = _create_library(pg_session)
        _create_song(pg_session, lib_id_a, "/music/a1.mp3")
        _create_song(pg_session, lib_id_a, "/music/a2.mp3")
        _create_song(pg_session, lib_id_b, "/music/b1.mp3")
        repo = SongRepository(pg_session)
        result = repo.list_songs(lib_id_a)
        assert len(result) == 2
        assert all(s["library_id"] == lib_id_a for s in result)

    def test_list_songs_with_limit(self, pg_session) -> None:
        """list_songs should respect limit parameter."""
        lib_id = _create_library(pg_session)
        for i in range(5):
            _create_song(pg_session, lib_id, f"/music/limit{i}.mp3")
        repo = SongRepository(pg_session)
        result = repo.list_songs(lib_id, limit=3)
        assert len(result) == 3

    def test_count_songs(self, pg_session) -> None:
        """count_songs should return the song count for a library."""
        lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/count1.mp3")
        _create_song(pg_session, lib_id, "/music/count2.mp3")
        repo = SongRepository(pg_session)
        result = repo.count_songs(lib_id)
        assert result >= 2

    def test_get_songs_by_ids(self, pg_session) -> None:
        """get_songs_by_ids should return songs for given ids."""
        lib_id = _create_library(pg_session)
        id1 = _create_song(pg_session, lib_id, "/music/batch1.mp3")
        id2 = _create_song(pg_session, lib_id, "/music/batch2.mp3")
        repo = SongRepository(pg_session)
        result = repo.get_songs_by_ids([id1, id2])
        assert len(result) == 2
        ids = {s["id"] for s in result}
        assert id1 in ids
        assert id2 in ids

    def test_get_library_ids_for_songs(self, pg_session) -> None:
        """get_library_ids_for_songs should return {song_id: library_id}."""
        lib_id = _create_library(pg_session)
        id1 = _create_song(pg_session, lib_id, "/music/map1.mp3")
        id2 = _create_song(pg_session, lib_id, "/music/map2.mp3")
        repo = SongRepository(pg_session)
        result = repo.get_library_ids_for_songs([id1, id2])
        assert result == {id1: lib_id, id2: lib_id}

    def test_list_library_song_ids(self, pg_session) -> None:
        """list_library_song_ids should return song ids for a library."""
        lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/lib1.mp3")
        _create_song(pg_session, lib_id, "/music/lib2.mp3")
        repo = SongRepository(pg_session)
        result = repo.list_library_song_ids(lib_id)
        assert len(result) >= 2

    def test_list_existing_song_paths(self, pg_session) -> None:
        """list_existing_song_paths should return paths that exist."""
        lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/existing.mp3")
        repo = SongRepository(pg_session)
        result = repo.list_existing_song_paths(
            lib_id,
            [
                "/music/existing.mp3",
                "/music/nonexistent.mp3",
            ],
        )
        assert "/music/existing.mp3" in result
        assert "/music/nonexistent.mp3" not in result

    def test_find_song_by_chromaprint(self, pg_session) -> None:
        """find_song_by_chromaprint should find song by chromaprint."""
        lib_id = _create_library(pg_session)
        song_id = _create_song(pg_session, lib_id, "/music/chroma.mp3")
        repo = SongRepository(pg_session)
        repo.update_song(song_id, {"chromaprint": "abc123"})
        result = repo.find_song_by_chromaprint(lib_id, "abc123")
        assert result is not None
        assert result["chromaprint"] == "abc123"

    def test_list_songs_for_folder(self, pg_session) -> None:
        """list_songs_for_folder should return songs in a folder."""
        lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/folder/file1.mp3", "folder/file1.mp3")
        _create_song(pg_session, lib_id, "/music/folder/file2.mp3", "folder/file2.mp3")
        _create_song(pg_session, lib_id, "/music/other/file3.mp3", "other/file3.mp3")
        repo = SongRepository(pg_session)
        result = repo.list_songs_for_folder(lib_id, "folder")
        assert len(result) == 2
        assert all(s["path"].startswith("/music/folder/") for s in result)
        assert {s["normalized_path"] for s in result} == {"folder/file1.mp3", "folder/file2.mp3"}

    def test_list_songs_for_folder_handles_root_and_library_scope(self, pg_session) -> None:
        """Folder queries should include root files and exclude other libraries."""
        lib_id = _create_library(pg_session)
        other_lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/root.mp3", "root.mp3")
        _create_song(pg_session, lib_id, "/music/folder/nested.mp3", "folder/nested.mp3")
        _create_song(pg_session, other_lib_id, "/music/other-root.mp3", "other-root.mp3")
        repo = SongRepository(pg_session)

        result = repo.list_songs_for_folder(lib_id, "")

        assert [song["normalized_path"] for song in result] == ["root.mp3"]
        assert [song["normalized_path"] for song in repo.list_songs_for_folder(lib_id, ".")] == ["root.mp3"]

    def test_list_songs_for_folder_escapes_like_wildcards(self, pg_session) -> None:
        """Folder wildcard characters should be matched literally."""
        lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/100%_complete/file1.mp3", "100%_complete/file1.mp3")
        _create_song(pg_session, lib_id, "/music/100Xacomplete/file2.mp3", "100Xacomplete/file2.mp3")
        repo = SongRepository(pg_session)

        result = repo.list_songs_for_folder(lib_id, "100%_complete")

        assert [song["path"] for song in result] == ["/music/100%_complete/file1.mp3"]

    def test_list_tracks_for_matching(self, pg_session) -> None:
        """list_tracks_for_matching should return songs ordered by id."""
        lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/match1.mp3")
        _create_song(pg_session, lib_id, "/music/match2.mp3")
        repo = SongRepository(pg_session)
        result = repo.list_tracks_for_matching(lib_id)
        ids = [s["id"] for s in result]
        assert ids == sorted(ids)

    def test_count_recently_tagged(self, pg_session) -> None:
        """count_recently_tagged should count songs tagged at/after cutoff."""
        lib_id = _create_library(pg_session)
        song_id = _create_song(pg_session, lib_id, "/music/recent.mp3")
        repo = SongRepository(pg_session)
        repo.update_song(song_id, {"last_tagged_at": 5000})
        assert repo.count_recently_tagged(4000) == 1
        assert repo.count_recently_tagged(6000) == 0

    # ── mutation / maintenance ──────────────────────────────────

    def test_remove_songs(self, pg_session) -> None:
        """remove_songs should delete multiple songs."""
        lib_id = _create_library(pg_session)
        id1 = _create_song(pg_session, lib_id, "/music/remove1.mp3")
        id2 = _create_song(pg_session, lib_id, "/music/remove2.mp3")
        repo = SongRepository(pg_session)
        repo.remove_songs([id1, id2])
        result = repo.get_songs_by_ids([id1, id2])
        assert len(result) == 0

    def test_list_orphaned_song_ids(self, pg_session) -> None:
        """list_orphaned_song_ids should return songs with missing library."""
        from sqlalchemy import text

        # Create library and song
        lib_id = _create_library(pg_session)
        song_id = _create_song(pg_session, lib_id, "/music/orphan.mp3")
        # Delete the library to create an orphan — temporarily disable FK checks
        # so SQLite doesn't cascade-delete the song (songs.library_id
        # has ondelete=CASCADE).  PostgreSQL uses ``SET session_replication_role``;
        # SQLite uses ``PRAGMA foreign_keys``.
        pg_session.execute(text("PRAGMA foreign_keys = OFF"))
        pg_session.execute(delete(Library).where(Library.id == lib_id))
        pg_session.execute(text("PRAGMA foreign_keys = ON"))
        pg_session.commit()
        repo = SongRepository(pg_session)
        result = repo.list_orphaned_song_ids()
        # Should find the orphaned song
        assert song_id in result

    def test_truncate_songs(self, pg_session) -> None:
        """truncate_songs should remove all song rows."""
        lib_id = _create_library(pg_session)
        _create_song(pg_session, lib_id, "/music/truncate.mp3")
        repo = SongRepository(pg_session)
        repo.truncate_songs()
        result = repo.count_songs(lib_id)
        assert result == 0

    def test_truncate_song_links(self, pg_session) -> None:
        """truncate_song_links should remove all song_tag rows."""
        from sqlalchemy import select

        from nomarr.persistence.models.song_tag import SongTag
        from nomarr.persistence.models.tag import Tag

        lib_id = _create_library(pg_session)
        song_id = _create_song(pg_session, lib_id)
        # Create a tag first
        tag_result = pg_session.execute(
            insert(Tag).values(
                name="test_tag",
                value="test_value",
                namespace="test_ns",
            )
        )
        tag_id = tag_result.inserted_primary_key[0]
        # Insert a song_tag
        pg_session.execute(
            insert(SongTag).values(
                song_id=song_id,
                tag_id=tag_id,
                confidence=0.9,
                source="ml",
                created_at=1000,
            )
        )
        pg_session.commit()
        repo = SongRepository(pg_session)
        repo.truncate_song_links()
        result = pg_session.execute(select(SongTag))
        assert len(result.all()) == 0


def _move_payload(
    *,
    path: str,
    normalized_path: str,
    file_size: int = 4321,
    modified_time: int = 8765,
    duration_seconds: float | None = 223.5,
    is_valid: int = 1,
    scanned_at: int = 5555,
) -> dict:
    """A canonical move payload mirroring the atomic-fields shape."""
    return {
        "path": path,
        "normalized_path": normalized_path,
        "file_size": file_size,
        "modified_time": modified_time,
        "duration_seconds": duration_seconds,
        "is_valid": is_valid,
        "scanned_at": scanned_at,
    }


@pytest.mark.unit
@pytest.mark.integration
class TestMoveSongAtomic:
    """``SongRepository.move_song`` single-statement atomicity on SQLite.

    SQLite enforces the same unique constraints (``uq_songs_library_path``,
    ``uq_songs_library_norm_path``) declared on the ORM model and the same
    single-``UPDATE`` semantics, so in-place all-field success, uniqueness
    rollback, and no-partial-row-state are deterministically provable here.
    PostgreSQL/DuplicateEntityError translation is covered by the facade-boundary
    mocks and the real-DB characterization suite.
    """

    def test_move_updates_all_fields_in_place_preserving_identity(self, pg_session) -> None:
        lib_id = _create_library(pg_session)
        song_id = _create_song(pg_session, lib_id, "/music/a.mp3")
        repo = SongRepository(pg_session)

        ok = repo.move_song(song_id, _move_payload(path="/music/z.mp3", normalized_path="z.mp3"))

        assert ok is True
        row = repo.get_song(song_id)
        assert row is not None
        # Same row (stable Song identity), same owning library — updated in place.
        assert row["id"] == song_id
        assert row["library_id"] == lib_id
        assert row["path"] == "/music/z.mp3"
        assert row["normalized_path"] == "z.mp3"
        assert row["file_size"] == 4321
        assert row["modified_time"] == 8765
        assert row["duration_seconds"] == 223.5
        assert row["is_valid"] == 1
        assert row["scanned_at"] == 5555

    def test_move_returns_false_and_writes_nothing_when_identity_missing(self, pg_session) -> None:
        lib_id = _create_library(pg_session)
        repo = SongRepository(pg_session)

        ok = repo.move_song(999999, _move_payload(path="/music/ghost.mp3", normalized_path="ghost.mp3"))

        assert ok is False
        # No replacement row is fabricated for a missing/stale identity.
        assert repo.get_song_by_path("/music/ghost.mp3", lib_id) is None

    def test_move_does_not_touch_unrelated_columns(self, pg_session) -> None:
        """A concurrent write to an unrelated column (e.g. chromaprint) is never
        clobbered by a move: the single UPDATE writes only the atomic columns."""
        lib_id = _create_library(pg_session)
        song_id = _create_song(pg_session, lib_id, "/music/a.mp3")
        repo = SongRepository(pg_session)
        # Simulate a separate writer having set an unrelated column.
        repo.update_song(song_id, {"chromaprint": "cp-123", "tagged": 1})
        baseline = repo.get_song(song_id)
        assert baseline is not None

        repo.move_song(song_id, _move_payload(path="/music/z.mp3", normalized_path="z.mp3"))

        row = repo.get_song(song_id)
        assert row is not None
        for col in (
            "library_id",
            "folder_id",
            "chromaprint",
            "needs_tagging",
            "tagged",
            "calibration_hash",
            "write_claimed_by",
            "last_tagged_at",
            "created_at",
        ):
            assert row[col] == baseline[col], f"move must not overwrite '{col}'"

    def test_path_uniqueness_conflict_leaves_original_row_unchanged(self, pg_session) -> None:
        lib_id = _create_library(pg_session)
        song_a = _create_song(pg_session, lib_id, "/music/a.mp3")
        _create_song(pg_session, lib_id, "/music/b.mp3")
        repo = SongRepository(pg_session)
        before = repo.get_song(song_a)
        assert before is not None

        with pytest.raises(DatabaseStateError):
            repo.move_song(song_a, _move_payload(path="/music/b.mp3", normalized_path="b.mp3"))

        # The move rolled back completely — no partial row state.
        after = repo.get_song(song_a)
        assert after is not None
        for col in (
            "path",
            "normalized_path",
            "file_size",
            "modified_time",
            "duration_seconds",
            "is_valid",
            "scanned_at",
        ):
            assert after[col] == before[col], f"'{col}' must roll back on uniqueness conflict"

    def test_normalized_path_uniqueness_conflict_rolls_back_whole_move(self, pg_session) -> None:
        lib_id = _create_library(pg_session)
        song_a = _create_song(pg_session, lib_id, "/music/a.mp3")
        _create_song(pg_session, lib_id, "/music/b.mp3", normalized_path="/music/b.mp3")
        repo = SongRepository(pg_session)
        before = repo.get_song(song_a)
        assert before is not None

        # Distinct physical path but colliding normalized_path → norm-path conflict.
        with pytest.raises(DatabaseStateError):
            repo.move_song(
                song_a,
                _move_payload(path="/music/c.mp3", normalized_path="/music/b.mp3"),
            )

        after = repo.get_song(song_a)
        assert after is not None
        assert after["path"] == "/music/a.mp3"
        assert after["normalized_path"] == "/music/a.mp3"
        assert after["file_size"] == before["file_size"]
        assert after["modified_time"] == before["modified_time"]

    def test_cross_library_path_collision_is_not_a_conflict(self, pg_session) -> None:
        """Uniqueness is scoped to (library_id, path): moving within the row's own
        library only conflicts with a sibling in THAT library."""
        lib1 = _create_library(pg_session)
        lib2 = _create_library(pg_session)
        song_a = _create_song(pg_session, lib1, "/music/a.mp3")
        # A same-path song in a different library does NOT block the move.
        _create_song(pg_session, lib2, "/music/b.mp3")

        repo = SongRepository(pg_session)
        assert repo.move_song(song_a, _move_payload(path="/music/b.mp3", normalized_path="b.mp3")) is True


@pytest.mark.unit
class TestMoveSongPersistenceBoundary:
    """Failure injection at the repo/session boundary (P3-S6): a failure either
    at statement execution (unique conflict on SQLite/Postgres) or at the final
    ``commit`` propagates out of ``move_song`` with the single statement never
    partially applied."""

    def _repo(self, session) -> SongRepository:
        return SongRepository(session)

    def test_commit_failure_propagates(self) -> None:
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = (1,)
        session.commit.side_effect = RuntimeError("commit failed")
        repo = self._repo(session)

        with pytest.raises(RuntimeError, match="commit failed"):
            repo.move_song(7, _move_payload(path="/music/z.mp3", normalized_path="z.mp3"))

        session.execute.assert_called_once()

    def test_statement_execution_failure_aborts_before_commit(self) -> None:
        session = MagicMock()
        session.execute.side_effect = IntegrityError("stmt", {}, Exception("dup"))
        repo = self._repo(session)

        with pytest.raises(DatabaseStateError):
            repo.move_song(7, _move_payload(path="/music/z.mp3", normalized_path="z.mp3"))

        session.commit.assert_not_called()
