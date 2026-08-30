"""Unit tests for EmbeddingStreamRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import func, insert, select

from nomarr.persistence.database.embedding_stream_repo import EmbeddingStreamRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.ml_embedding_stream import MlEmbeddingStream
from nomarr.persistence.models.song import Song


def _insert_library(session) -> int:
    """Insert a library row and return its id."""
    stmt = (
        insert(Library)
        .values(
            name="ES Test Library",
            path="/music/es_test",
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


def _insert_song(session, library_id: int, path: str = "/music/es_test/file.mp3") -> int:
    """Insert a song row and return its id."""
    stmt = (
        insert(Song)
        .values(
            library_id=library_id,
            path=path,
            normalized_path=path,
            file_size=1024,
            modified_time=1000,
            created_at=1000,
        )
        .returning(Song.id)
    )
    result = session.execute(stmt)
    return int(result.scalar_one())


@pytest.mark.unit
@pytest.mark.integration
class TestEmbeddingStreamRepository:
    """Tests for EmbeddingStreamRepository CRUD and query methods."""

    def test_upsert_stream_insert(self, pg_session) -> None:
        """upsert_stream should insert a new embedding stream."""
        lib_id = _insert_library(pg_session)
        song_id = _insert_song(pg_session, lib_id)
        repo = EmbeddingStreamRepository(pg_session)

        record = repo.upsert_stream(
            song_id=song_id,
            backbone="bb_test",
            patches_emb=b"\x00\x01\x02",
        )
        assert record["id"] > 0
        assert record["song_id"] == song_id
        assert record["backbone"] == "bb_test"
        assert record["patches_emb"] == b"\x00\x01\x02"
        assert record["created_at"] > 0
        # model has no updated_at column — DTO always maps it to None
        assert record["updated_at"] is None

    def test_upsert_stream_update(self, pg_session) -> None:
        """upsert_stream should update an existing stream for the same (file, backbone)."""
        lib_id = _insert_library(pg_session)
        song_id = _insert_song(pg_session, lib_id)
        repo = EmbeddingStreamRepository(pg_session)

        repo.upsert_stream(song_id, "bb_upd", b"\x00")
        updated = repo.upsert_stream(song_id, "bb_upd", b"\xff\xfe")
        assert updated["song_id"] == song_id
        assert updated["backbone"] == "bb_upd"
        assert updated["patches_emb"] == b"\xff\xfe"

    def test_upsert_stream_enforces_single_row(self, pg_session) -> None:
        """upsert_stream must leave exactly one row per (song, backbone) pair."""
        lib_id = _insert_library(pg_session)
        song_id = _insert_song(pg_session, lib_id)
        repo = EmbeddingStreamRepository(pg_session)

        repo.upsert_stream(song_id, "bb_unique", b"\x01")
        repo.upsert_stream(song_id, "bb_unique", b"\x02")

        count_stmt = (
            select(func.count())
            .select_from(MlEmbeddingStream.__table__)
            .where(
                MlEmbeddingStream.__table__.c.song_id == song_id,
                MlEmbeddingStream.__table__.c.backbone_id == "bb_unique",
            )
        )
        assert pg_session.execute(count_stmt).scalar_one() == 1
        stream = repo.get_stream(song_id, "bb_unique")
        assert stream is not None
        assert stream["patches_emb"] == b"\x02"

    def test_get_stream_existing(self, pg_session) -> None:
        """get_stream should return the stream for an existing (file, backbone) pair."""
        lib_id = _insert_library(pg_session)
        song_id = _insert_song(pg_session, lib_id)
        repo = EmbeddingStreamRepository(pg_session)

        repo.upsert_stream(song_id, "bb_get", b"\xab")
        result = repo.get_stream(song_id, "bb_get")
        assert result is not None
        assert result["song_id"] == song_id
        assert result["backbone"] == "bb_get"
        assert result["patches_emb"] == b"\xab"

    def test_get_stream_nonexistent(self, pg_session) -> None:
        """get_stream should return None for a missing (file, backbone) pair."""
        repo = EmbeddingStreamRepository(pg_session)
        result = repo.get_stream(999999, "no_backbone")
        assert result is None

    def test_list_by_backbone(self, pg_session) -> None:
        """list_by_backbone should return streams for a given backbone."""
        lib_id = _insert_library(pg_session)
        song_id_1 = _insert_song(pg_session, lib_id, "/music/es_test/f1.mp3")
        song_id_2 = _insert_song(pg_session, lib_id, "/music/es_test/f2.mp3")
        repo = EmbeddingStreamRepository(pg_session)

        repo.upsert_stream(song_id_1, "bb_list", b"\x01")
        repo.upsert_stream(song_id_2, "bb_list", b"\x02")
        repo.upsert_stream(song_id_1, "bb_other", b"\x03")

        results = repo.list_by_backbone("bb_list")
        assert len(results) == 2
        song_ids = {r["song_id"] for r in results}
        assert song_ids == {song_id_1, song_id_2}

    def test_list_by_backbone_with_pagination(self, pg_session) -> None:
        """list_by_backbone should support limit and offset."""
        lib_id = _insert_library(pg_session)
        repo = EmbeddingStreamRepository(pg_session)

        # Insert 5 streams for the same backbone
        for i in range(5):
            sid = _insert_song(pg_session, lib_id, f"/music/es_test/pg_{i}.mp3")
            repo.upsert_stream(sid, "bb_page", bytes([i]))

        # Get first 2
        page_1 = repo.list_by_backbone("bb_page", limit=2, offset=0)
        assert len(page_1) == 2

        # Get next 2
        page_2 = repo.list_by_backbone("bb_page", limit=2, offset=2)
        assert len(page_2) == 2

        # Ensure no overlap
        ids_1 = {r["id"] for r in page_1}
        ids_2 = {r["id"] for r in page_2}
        assert ids_1.isdisjoint(ids_2)

    def test_delete_for_song(self, pg_session) -> None:
        """delete_for_song should remove all streams for a given song."""
        lib_id = _insert_library(pg_session)
        song_id = _insert_song(pg_session, lib_id)
        repo = EmbeddingStreamRepository(pg_session)

        repo.upsert_stream(song_id, "bb_del_1", b"\x01")
        repo.upsert_stream(song_id, "bb_del_2", b"\x02")

        repo.delete_for_song(song_id)
        assert repo.get_stream(song_id, "bb_del_1") is None
        assert repo.get_stream(song_id, "bb_del_2") is None
