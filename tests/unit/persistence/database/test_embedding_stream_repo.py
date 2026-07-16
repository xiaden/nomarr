"""Unit tests for EmbeddingStreamRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from nomarr.persistence.database.embedding_stream_repo import EmbeddingStreamRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile


async def _insert_library(session) -> int:
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
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def _insert_library_file(session, library_id: int, path: str = "/music/es_test/file.mp3") -> int:
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
    result = await session.execute(stmt)
    return int(result.scalar_one())


@pytest.mark.unit
@pytest.mark.integration
class TestEmbeddingStreamRepository:
    """Tests for EmbeddingStreamRepository CRUD and query methods."""

    @pytest.mark.asyncio
    async def test_upsert_stream_insert(self, pg_session) -> None:
        """upsert_stream should insert a new embedding stream."""
        lib_id = await _insert_library(pg_session)
        file_id = await _insert_library_file(pg_session, lib_id)
        repo = EmbeddingStreamRepository(pg_session)

        record = await repo.upsert_stream(
            file_id=file_id,
            backbone="bb_test",
            stream_payload={"patches_emb": b"\x00\x01\x02"},
        )
        assert record["id"] > 0
        assert record["file_id"] == file_id
        assert record["backbone"] == "bb_test"
        assert record["patches_emb"] == b"\x00\x01\x02"
        assert record["created_at"] > 0
        # model has no updated_at column — DTO always maps it to None
        assert record["updated_at"] is None

    @pytest.mark.asyncio
    async def test_upsert_stream_update(self, pg_session) -> None:
        """upsert_stream should update an existing stream for the same (file, backbone)."""
        lib_id = await _insert_library(pg_session)
        file_id = await _insert_library_file(pg_session, lib_id)
        repo = EmbeddingStreamRepository(pg_session)

        await repo.upsert_stream(file_id, "bb_upd", {"patches_emb": b"\x00"})
        updated = await repo.upsert_stream(file_id, "bb_upd", {"patches_emb": b"\xff\xfe"})
        assert updated["file_id"] == file_id
        assert updated["backbone"] == "bb_upd"
        assert updated["patches_emb"] == b"\xff\xfe"

    @pytest.mark.asyncio
    async def test_get_stream_existing(self, pg_session) -> None:
        """get_stream should return the stream for an existing (file, backbone) pair."""
        lib_id = await _insert_library(pg_session)
        file_id = await _insert_library_file(pg_session, lib_id)
        repo = EmbeddingStreamRepository(pg_session)

        await repo.upsert_stream(file_id, "bb_get", {"patches_emb": b"\xab"})
        result = await repo.get_stream(file_id, "bb_get")
        assert result is not None
        assert result["file_id"] == file_id
        assert result["backbone"] == "bb_get"
        assert result["patches_emb"] == b"\xab"

    @pytest.mark.asyncio
    async def test_get_stream_nonexistent(self, pg_session) -> None:
        """get_stream should return None for a missing (file, backbone) pair."""
        repo = EmbeddingStreamRepository(pg_session)
        result = await repo.get_stream(999999, "no_backbone")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_by_backbone(self, pg_session) -> None:
        """list_by_backbone should return streams for a given backbone."""
        lib_id = await _insert_library(pg_session)
        file_id_1 = await _insert_library_file(pg_session, lib_id, "/music/es_test/f1.mp3")
        file_id_2 = await _insert_library_file(pg_session, lib_id, "/music/es_test/f2.mp3")
        repo = EmbeddingStreamRepository(pg_session)

        await repo.upsert_stream(file_id_1, "bb_list", {"patches_emb": b"\x01"})
        await repo.upsert_stream(file_id_2, "bb_list", {"patches_emb": b"\x02"})
        await repo.upsert_stream(file_id_1, "bb_other", {"patches_emb": b"\x03"})

        results = await repo.list_by_backbone("bb_list")
        assert len(results) == 2
        file_ids = {r["file_id"] for r in results}
        assert file_ids == {file_id_1, file_id_2}

    @pytest.mark.asyncio
    async def test_list_by_backbone_with_pagination(self, pg_session) -> None:
        """list_by_backbone should support limit and offset."""
        lib_id = await _insert_library(pg_session)
        repo = EmbeddingStreamRepository(pg_session)

        # Insert 5 streams for the same backbone
        for i in range(5):
            fid = await _insert_library_file(pg_session, lib_id, f"/music/es_test/pg_{i}.mp3")
            await repo.upsert_stream(fid, "bb_page", {"patches_emb": bytes([i])})

        # Get first 2
        page_1 = await repo.list_by_backbone("bb_page", limit=2, offset=0)
        assert len(page_1) == 2

        # Get next 2
        page_2 = await repo.list_by_backbone("bb_page", limit=2, offset=2)
        assert len(page_2) == 2

        # Ensure no overlap
        ids_1 = {r["id"] for r in page_1}
        ids_2 = {r["id"] for r in page_2}
        assert ids_1.isdisjoint(ids_2)

    @pytest.mark.asyncio
    async def test_delete_for_file(self, pg_session) -> None:
        """delete_for_file should remove all streams for a given file."""
        lib_id = await _insert_library(pg_session)
        file_id = await _insert_library_file(pg_session, lib_id)
        repo = EmbeddingStreamRepository(pg_session)

        await repo.upsert_stream(file_id, "bb_del_1", {"patches_emb": b"\x01"})
        await repo.upsert_stream(file_id, "bb_del_2", {"patches_emb": b"\x02"})

        await repo.delete_for_file(file_id)
        assert await repo.get_stream(file_id, "bb_del_1") is None
        assert await repo.get_stream(file_id, "bb_del_2") is None
