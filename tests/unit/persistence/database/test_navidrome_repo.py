"""Unit tests for NavidromeRepo."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from nomarr.persistence.database.navidrome_repo import NavidromeRepo
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile


def _insert_library(session) -> int:
    """Insert a library row and return its id."""
    stmt = (
        insert(Library)
        .values(
            name="ND Test Library",
            path="/music/nd_test",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
        .returning(Library.id)
    )
    result = session.execute(stmt)
    return int(result.scalar_one())


def _insert_library_file(session, library_id: int, path: str = "/music/nd_test/file.mp3") -> int:
    """Insert a library file row and return its id."""
    stmt = (
        insert(LibraryFile)
        .values(
            library_id=library_id,
            path=path,
            normalized_path=path,
            file_size=1024,
            modified_time=1000,
            created_at=1000,
        )
        .returning(LibraryFile.id)
    )
    result = session.execute(stmt)
    return int(result.scalar_one())


@pytest.mark.unit
@pytest.mark.integration
class TestNavidromeRepo:
    """Tests for NavidromeRepo CRUD and query methods."""

    def test_upsert_track_insert(self, pg_session) -> None:
        """upsert_track should insert a new track."""
        repo = NavidromeRepo(pg_session)
        record = repo.upsert_track(
            nd_id="nd_1",
            title="Song A",
            artist="Artist A",
            album="Album A",
            file_path="/music/a.mp3",
        )
        assert record["id"] == "nd_1"
        assert record["title"] == "Song A"
        assert record["artist"] == "Artist A"
        assert record["album"] == "Album A"
        assert record["file_path"] == "/music/a.mp3"
        assert record["created_at"] > 0

    def test_upsert_track_update(self, pg_session) -> None:
        """upsert_track should update an existing track on conflict."""
        repo = NavidromeRepo(pg_session)
        repo.upsert_track("nd_upd", "Old Title", "Old Artist", "Old Album", "/old.mp3")
        updated = repo.upsert_track("nd_upd", "New Title", "New Artist", "New Album", "/new.mp3")
        assert updated["id"] == "nd_upd"
        assert updated["title"] == "New Title"
        assert updated["artist"] == "New Artist"

    def test_upsert_track_null_coercion(self, pg_session) -> None:
        """upsert_track should coerce None values to empty strings."""
        repo = NavidromeRepo(pg_session)
        record = repo.upsert_track("nd_null", None, None, None, None)
        assert record["title"] == ""
        assert record["artist"] == ""
        assert record["album"] == ""
        assert record["file_path"] == ""

    def test_get_track_existing(self, pg_session) -> None:
        """get_track should return the track for an existing nd_id."""
        repo = NavidromeRepo(pg_session)
        repo.upsert_track("nd_get", "Title", "Artist", "Album", "/path.mp3")
        result = repo.get_track("nd_get")
        assert result is not None
        assert result["id"] == "nd_get"
        assert result["title"] == "Title"

    def test_get_track_nonexistent(self, pg_session) -> None:
        """get_track should return None for a missing nd_id."""
        repo = NavidromeRepo(pg_session)
        result = repo.get_track("no_such_track")
        assert result is None

    def test_list_nd_track_keys(self, pg_session) -> None:
        """list_nd_track_keys should return all track IDs."""
        repo = NavidromeRepo(pg_session)
        repo.upsert_track("keys_1", "T1", "A1", "Al1", "/p1.mp3")
        repo.upsert_track("keys_2", "T2", "A2", "Al2", "/p2.mp3")
        keys = repo.list_nd_track_keys()
        assert "keys_1" in keys
        assert "keys_2" in keys

    def test_map_track_to_file(self, pg_session) -> None:
        """map_track_to_file should create a track-to-file mapping."""
        lib_id = _insert_library(pg_session)
        file_id = _insert_library_file(pg_session, lib_id)
        repo = NavidromeRepo(pg_session)
        repo.upsert_track("nd_map", "Title", "Artist", "Album", "/path.mp3")
        repo.map_track_to_file("nd_map", file_id)
        result = repo.get_mapped_file("nd_map")
        assert result == file_id

    def test_get_mapped_file_nonexistent(self, pg_session) -> None:
        """get_mapped_file should return None when no mapping exists."""
        repo = NavidromeRepo(pg_session)
        result = repo.get_mapped_file("unmapped_track")
        assert result is None

    def test_resolve_file_to_nd_track(self, pg_session) -> None:
        """resolve_file_to_nd_track should reverse-lookup a track by file_id."""
        lib_id = _insert_library(pg_session)
        file_id = _insert_library_file(pg_session, lib_id)
        repo = NavidromeRepo(pg_session)
        repo.upsert_track("nd_resolve", "Title", "Artist", "Album", "/path.mp3")
        repo.map_track_to_file("nd_resolve", file_id)
        result = repo.resolve_file_to_nd_track(file_id)
        assert result == "nd_resolve"

    def test_resolve_file_to_nd_track_nonexistent(self, pg_session) -> None:
        """resolve_file_to_nd_track should return None for unmapped file."""
        repo = NavidromeRepo(pg_session)
        result = repo.resolve_file_to_nd_track(999999)
        assert result is None

    def test_bulk_upsert_tracks(self, pg_session) -> None:
        """bulk_upsert_tracks should insert multiple track stubs."""
        repo = NavidromeRepo(pg_session)
        count = repo.bulk_upsert_tracks(["bulk_1", "bulk_2", "bulk_3"])
        assert count == 3
        keys = repo.list_nd_track_keys()
        assert "bulk_1" in keys
        assert "bulk_2" in keys
        assert "bulk_3" in keys

    def test_bulk_upsert_tracks_empty(self, pg_session) -> None:
        """bulk_upsert_tracks should return 0 for empty input."""
        repo = NavidromeRepo(pg_session)
        count = repo.bulk_upsert_tracks([])
        assert count == 0

    def test_bulk_map_tracks(self, pg_session) -> None:
        """bulk_map_tracks should insert multiple track-to-file mappings."""
        lib_id = _insert_library(pg_session)
        file_id_1 = _insert_library_file(pg_session, lib_id, "/music/nd_test/b1.mp3")
        file_id_2 = _insert_library_file(pg_session, lib_id, "/music/nd_test/b2.mp3")
        repo = NavidromeRepo(pg_session)
        repo.bulk_upsert_tracks(["bm_1", "bm_2"])

        mappings = [
            {"nd_id": "bm_1", "file_id": str(file_id_1)},
            {"nd_id": "bm_2", "file_id": str(file_id_2)},
        ]
        count = repo.bulk_map_tracks(mappings)
        assert count == 2
        assert repo.get_mapped_file("bm_1") == file_id_1
        assert repo.get_mapped_file("bm_2") == file_id_2

    def test_bulk_map_tracks_empty(self, pg_session) -> None:
        """bulk_map_tracks should return 0 for empty input."""
        repo = NavidromeRepo(pg_session)
        count = repo.bulk_map_tracks([])
        assert count == 0

    def test_record_play(self, pg_session) -> None:
        """record_play should insert a play event and return its id."""
        repo = NavidromeRepo(pg_session)
        repo.upsert_track("nd_play", "Title", "Artist", "Album", "/path.mp3")
        play_id = repo.record_play(
            nd_id="nd_play",
            user_id="user_1",
            played_at=5000,
        )
        assert isinstance(play_id, int)
        assert play_id > 0

    def test_record_play_with_file(self, pg_session) -> None:
        """record_play with file_id should also create a play-to-file mapping."""
        lib_id = _insert_library(pg_session)
        file_id = _insert_library_file(pg_session, lib_id)
        repo = NavidromeRepo(pg_session)
        repo.upsert_track("nd_playf", "Title", "Artist", "Album", "/path.mp3")
        play_id = repo.record_play(
            nd_id="nd_playf",
            user_id="user_1",
            played_at=6000,
            file_id=file_id,
        )
        assert play_id > 0

    def test_get_top_plays(self, pg_session) -> None:
        """get_top_plays should return aggregated play counts for a user."""
        lib_id = _insert_library(pg_session)
        file_id = _insert_library_file(pg_session, lib_id)
        repo = NavidromeRepo(pg_session)
        repo.upsert_track("nd_top", "Title", "Artist", "Album", "/path.mp3")

        # Record 3 plays for the same track/file/user
        for i in range(3):
            repo.record_play(
                nd_id="nd_top",
                user_id="top_user",
                played_at=7000 + i,
                file_id=file_id,
            )

        results = repo.get_top_plays("top_user", top_n=10)
        assert len(results) >= 1
        matching = [r for r in results if r["nd_id"] == "nd_top"]
        assert len(matching) == 1
        assert matching[0]["playcount"] == 3
        assert matching[0]["last_played"] == 7002

    def test_delete_tracks_for_file(self, pg_session) -> None:
        """delete_tracks_for_file should remove track mappings for a file."""
        lib_id = _insert_library(pg_session)
        file_id = _insert_library_file(pg_session, lib_id)
        repo = NavidromeRepo(pg_session)
        repo.upsert_track("nd_delf", "Title", "Artist", "Album", "/path.mp3")
        repo.map_track_to_file("nd_delf", file_id)

        deleted = repo.delete_tracks_for_file(file_id)
        assert deleted == 1
        result = repo.get_mapped_file("nd_delf")
        assert result is None
