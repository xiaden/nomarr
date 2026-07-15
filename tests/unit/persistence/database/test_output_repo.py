"""Unit tests for OutputRepo."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from nomarr.persistence.database.output_repo import OutputRepo
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile
from nomarr.persistence.models.ml_model import MlModel


async def _insert_library(session) -> int:
    """Insert a library row and return its id."""
    stmt = (
        insert(Library)
        .values(
            name="Test Library",
            path="/music/test",
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


async def _insert_library_file(session, library_id: int) -> int:
    """Insert a library file row and return its id."""
    stmt = (
        insert(LibraryFile)
        .values(
            library_id=library_id,
            path="/music/test/file.mp3",
            normalized_path="/music/test/file.mp3",
            file_size=1024,
            modified_time=1000,
            created_at=1000,
        )
        .returning(LibraryFile.id)
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def _insert_model(session, model_id: str = "test_model") -> str:
    """Insert a model row and return its id."""
    stmt = (
        insert(MlModel)
        .values(
            id=model_id,
            model_type="genre",
            backbone_id="bb_1",
            enabled=1,
            created_at=1000,
            updated_at=1000,
        )
        .returning(MlModel.id)
    )
    result = await session.execute(stmt)
    return str(result.scalar_one())


@pytest.mark.unit
@pytest.mark.integration
class TestOutputRepo:
    """Tests for OutputRepo CRUD and query methods."""

    @pytest.mark.asyncio
    async def test_store_model_output(self, pg_session) -> None:
        """store_model_output should insert and return the output record."""
        lib_id = await _insert_library(pg_session)
        file_id = await _insert_library_file(pg_session, lib_id)
        await _insert_model(pg_session, "out_model_1")

        repo = OutputRepo(pg_session)
        record = await repo.store_model_output(
            file_id=file_id,
            model_id="out_model_1",
            output_data={"genre": "rock", "confidence": 0.9},
        )
        assert record["id"] > 0
        assert record["file_id"] == file_id
        assert record["model_id"] == "out_model_1"
        assert record["output_data"]["genre"] == "rock"
        assert record["created_at"] > 0

    @pytest.mark.asyncio
    async def test_store_output_stream(self, pg_session) -> None:
        """store_output_stream should insert and return the stream record."""
        lib_id = await _insert_library(pg_session)
        file_id = await _insert_library_file(pg_session, lib_id)
        await _insert_model(pg_session, "stream_model_1")

        repo = OutputRepo(pg_session)
        record = await repo.store_output_stream(
            file_id=file_id,
            model_id="stream_model_1",
            status="pending",
        )
        assert record["id"] > 0
        assert record["file_id"] == file_id
        assert record["model_id"] == "stream_model_1"
        assert record["status"] == "pending"
        assert record["created_at"] > 0

    @pytest.mark.asyncio
    async def test_get_output_existing(self, pg_session) -> None:
        """get_output should return the record for an existing output id."""
        lib_id = await _insert_library(pg_session)
        file_id = await _insert_library_file(pg_session, lib_id)
        await _insert_model(pg_session, "get_model")

        repo = OutputRepo(pg_session)
        stored = await repo.store_model_output(
            file_id=file_id,
            model_id="get_model",
            output_data={"key": "value"},
        )
        result = await repo.get_output(stored["id"])
        assert result is not None
        assert result["id"] == stored["id"]
        assert result["output_data"]["key"] == "value"

    @pytest.mark.asyncio
    async def test_get_output_nonexistent(self, pg_session) -> None:
        """get_output should return None for a missing output id."""
        repo = OutputRepo(pg_session)
        result = await repo.get_output(999999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_outputs_for_file(self, pg_session) -> None:
        """get_outputs_for_file should return all outputs for a file."""
        lib_id = await _insert_library(pg_session)
        file_id = await _insert_library_file(pg_session, lib_id)
        await _insert_model(pg_session, "file_model_a")
        await _insert_model(pg_session, "file_model_b")

        repo = OutputRepo(pg_session)
        await repo.store_model_output(file_id, "file_model_a", {"a": 1})
        await repo.store_model_output(file_id, "file_model_b", {"b": 2})

        results = await repo.get_outputs_for_file(file_id)
        assert len(results) == 2
        model_ids = {r["model_id"] for r in results}
        assert model_ids == {"file_model_a", "file_model_b"}

    @pytest.mark.asyncio
    async def test_list_model_outputs(self, pg_session) -> None:
        """list_model_outputs should return all outputs for a model."""
        lib_id = await _insert_library(pg_session)
        file_id_1 = await _insert_library_file(pg_session, lib_id)
        stmt = (
            insert(LibraryFile)
            .values(
                library_id=lib_id,
                path="/music/test/file2.mp3",
                normalized_path="/music/test/file2.mp3",
                file_size=2048,
                modified_time=2000,
                created_at=2000,
            )
            .returning(LibraryFile.id)
        )
        result = await pg_session.execute(stmt)
        file_id_2 = result.scalar_one()
        await _insert_model(pg_session, "list_model")

        repo = OutputRepo(pg_session)
        await repo.store_model_output(file_id_1, "list_model", {"f": 1})
        await repo.store_model_output(file_id_2, "list_model", {"f": 2})

        results = await repo.list_model_outputs("list_model")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_delete_output(self, pg_session) -> None:
        """delete_output should remove a single output by id."""
        lib_id = await _insert_library(pg_session)
        file_id = await _insert_library_file(pg_session, lib_id)
        await _insert_model(pg_session, "del_model")

        repo = OutputRepo(pg_session)
        stored = await repo.store_model_output(file_id, "del_model", {"x": 1})
        await repo.delete_output(stored["id"])
        result = await repo.get_output(stored["id"])
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_outputs_for_model(self, pg_session) -> None:
        """delete_outputs_for_model should remove all outputs for a model."""
        lib_id = await _insert_library(pg_session)
        file_id = await _insert_library_file(pg_session, lib_id)
        await _insert_model(pg_session, "del_fm")

        repo = OutputRepo(pg_session)
        await repo.store_model_output(file_id, "del_fm", {"a": 1})
        await repo.store_model_output(file_id, "del_fm", {"b": 2})

        deleted = await repo.delete_outputs_for_model("del_fm")
        assert deleted == 2
        results = await repo.list_model_outputs("del_fm")
        assert results == []

    @pytest.mark.asyncio
    async def test_delete_outputs_for_file(self, pg_session) -> None:
        """delete_outputs_for_file should remove all outputs for a file."""
        lib_id = await _insert_library(pg_session)
        file_id = await _insert_library_file(pg_session, lib_id)
        await _insert_model(pg_session, "del_ff_a")
        await _insert_model(pg_session, "del_ff_b")

        repo = OutputRepo(pg_session)
        await repo.store_model_output(file_id, "del_ff_a", {"a": 1})
        await repo.store_model_output(file_id, "del_ff_b", {"b": 2})

        deleted = await repo.delete_outputs_for_file(file_id)
        assert deleted == 2
        results = await repo.get_outputs_for_file(file_id)
        assert results == []
