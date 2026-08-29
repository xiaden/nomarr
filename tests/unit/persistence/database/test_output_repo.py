"""Unit tests for OutputRepo."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from nomarr.persistence.database.output_repo import OutputRepo
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.ml_model import MlModel
from nomarr.persistence.models.song import Song


def _insert_library(session) -> int:
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
    result = session.execute(stmt)
    return int(result.scalar_one())


def _insert_song(session, library_id: int) -> int:
    """Insert a song row and return its id."""
    stmt = (
        insert(Song)
        .values(
            library_id=library_id,
            path="/music/test/file.mp3",
            normalized_path="/music/test/file.mp3",
            file_size=1024,
            modified_time=1000,
            created_at=1000,
        )
        .returning(Song.id)
    )
    result = session.execute(stmt)
    return int(result.scalar_one())


def _insert_model(session, model_id: str = "test_model") -> str:
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
    result = session.execute(stmt)
    return str(result.scalar_one())


@pytest.mark.unit
@pytest.mark.integration
class TestOutputRepo:
    """Tests for OutputRepo CRUD and query methods."""

    def test_store_model_output(self, pg_session) -> None:
        """store_model_output should insert and return the output record."""
        lib_id = _insert_library(pg_session)
        _insert_song(pg_session, lib_id)
        _insert_model(pg_session, "out_model_1")

        repo = OutputRepo(pg_session)
        record = repo.store_model_output(
            model_id="out_model_1",
            output_id="output_1",
            output_data={"genre": "rock", "confidence": 0.9},
        )
        assert record["id"] > 0
        assert record["output_id"] == "output_1"
        assert record["model_id"] == "out_model_1"
        assert record["output_data"]["genre"] == "rock"
        assert record["created_at"] > 0

    def test_store_model_output_updates_existing_by_output_id(self, pg_session) -> None:
        """Storing again with the same output_id updates the row, not a second insert."""
        lib_id = _insert_library(pg_session)
        _insert_song(pg_session, lib_id)
        _insert_model(pg_session, "upsert_model")

        repo = OutputRepo(pg_session)
        first = repo.store_model_output(
            model_id="upsert_model",
            output_id="output_1",
            output_data={"genre": "rock"},
            output_index=0,
            label=None,
            fully_labeled=False,
        )
        updated = repo.store_model_output(
            model_id="upsert_model",
            output_id="output_1",
            output_data={"genre": "jazz"},
            output_index=0,
            label="moody",
            fully_labeled=True,
        )

        assert updated["id"] == first["id"]
        assert updated["output_id"] == "output_1"
        assert updated["output_data"]["genre"] == "jazz"
        assert updated["label"] == "moody"
        assert updated["fully_labeled"] is True
        assert len(repo.list_model_outputs("upsert_model")) == 1
        assert repo.get_output("output_1")["output_data"]["genre"] == "jazz"

    def test_store_output_stream(self, pg_session) -> None:
        """store_output_stream should insert and return the canonical stream record."""
        lib_id = _insert_library(pg_session)
        song_id = _insert_song(pg_session, lib_id)

        repo = OutputRepo(pg_session)
        record = repo.store_output_stream(
            song_id=song_id,
            output_id="output_1",
            values=[0.1, 0.2, 0.3],
            output_index=0,
        )
        assert record["id"] > 0
        assert record["song_id"] == song_id
        assert record["output_id"] == "output_1"
        assert record["output_index"] == 0
        assert record["values"] == [0.1, 0.2, 0.3]
        assert record["created_at"] > 0

    def test_list_output_streams_for_song_round_trips(self, pg_session) -> None:
        """list_output_streams_for_song should round-trip canonical {output_id, values}."""
        lib_id = _insert_library(pg_session)
        song_id = _insert_song(pg_session, lib_id)

        repo = OutputRepo(pg_session)
        repo.store_output_stream(song_id, output_id="output_a", values=[0.5, 0.6], output_index=0)
        repo.store_output_stream(song_id, output_id="output_b", values=[0.7, 0.8], output_index=1)

        results = repo.list_output_streams_for_song(song_id)
        assert len(results) == 2
        by_id = {r["output_id"]: r for r in results}
        assert by_id["output_a"]["values"] == [0.5, 0.6]
        assert by_id["output_a"]["output_index"] == 0
        assert by_id["output_b"]["values"] == [0.7, 0.8]
        assert by_id["output_b"]["output_index"] == 1

    def test_list_output_streams_for_song_nonexistent(self, pg_session) -> None:
        """list_output_streams_for_song should return [] for a song with no streams."""
        repo = OutputRepo(pg_session)
        assert repo.list_output_streams_for_song(999999) == []

    def test_delete_output_streams_for_song_scopes_to_song(self, pg_session) -> None:
        """delete_output_streams_for_song should remove only that song's streams."""
        lib_id = _insert_library(pg_session)
        song_id_1 = _insert_song(pg_session, lib_id)
        song_r = pg_session.execute(
            insert(Song)
            .values(
                library_id=lib_id,
                path="/music/test/stream2.mp3",
                normalized_path="/music/test/stream2.mp3",
                file_size=2048,
                modified_time=2000,
                created_at=2000,
            )
            .returning(Song.id)
        )
        song_id_2 = song_r.scalar_one()

        repo = OutputRepo(pg_session)
        repo.store_output_stream(song_id_1, output_id="a", values=[1.0], output_index=0)
        repo.store_output_stream(song_id_2, output_id="b", values=[2.0], output_index=0)

        deleted = repo.delete_output_streams_for_song(song_id_1)
        assert deleted == 1
        assert repo.list_output_streams_for_song(song_id_1) == []
        assert len(repo.list_output_streams_for_song(song_id_2)) == 1

    def test_get_output_existing(self, pg_session) -> None:
        """get_output should return the record for an existing output id."""
        lib_id = _insert_library(pg_session)
        _insert_song(pg_session, lib_id)
        _insert_model(pg_session, "get_model")

        repo = OutputRepo(pg_session)
        stored = repo.store_model_output(
            model_id="get_model",
            output_id="get_output",
            output_data={"key": "value"},
        )
        result = repo.get_output("get_output")
        assert result is not None
        assert result["id"] == stored["id"]
        assert result["output_data"]["key"] == "value"

    def test_get_output_nonexistent(self, pg_session) -> None:
        """get_output should return None for a missing output id."""
        repo = OutputRepo(pg_session)
        result = repo.get_output("missing")
        assert result is None

    def test_list_model_outputs(self, pg_session) -> None:
        """list_model_outputs should return all outputs for a model, ordered by index."""
        lib_id = _insert_library(pg_session)
        _insert_song(pg_session, lib_id)
        _insert_model(pg_session, "list_model")

        repo = OutputRepo(pg_session)
        repo.store_model_output("list_model", "list_a", {"f": 1}, output_index=0)
        repo.store_model_output("list_model", "list_b", {"f": 2}, output_index=1)

        results = repo.list_model_outputs("list_model")
        assert len(results) == 2
        assert [r["output_id"] for r in results] == ["list_a", "list_b"]

    def test_list_model_outputs_orders_by_output_index(self, pg_session) -> None:
        """list_model_outputs should order rows by output_index ascending."""
        lib_id = _insert_library(pg_session)
        _insert_song(pg_session, lib_id)
        _insert_model(pg_session, "order_model")

        repo = OutputRepo(pg_session)
        repo.store_model_output("order_model", "late", {"f": 3}, output_index=2)
        repo.store_model_output("order_model", "early", {"f": 1}, output_index=0)

        results = repo.list_model_outputs("order_model")
        assert [r["output_id"] for r in results] == ["early", "late"]

    def test_delete_output(self, pg_session) -> None:
        """delete_output should remove a single output by id."""
        lib_id = _insert_library(pg_session)
        _insert_song(pg_session, lib_id)
        _insert_model(pg_session, "del_model")

        repo = OutputRepo(pg_session)
        repo.store_model_output("del_model", "delete_output", {"x": 1})
        repo.delete_output("delete_output")
        result = repo.get_output("delete_output")
        assert result is None

    def test_delete_outputs_for_model(self, pg_session) -> None:
        """delete_outputs_for_model should remove all outputs for a model and return their ids."""
        lib_id = _insert_library(pg_session)
        _insert_song(pg_session, lib_id)
        _insert_model(pg_session, "del_fm")

        repo = OutputRepo(pg_session)
        repo.store_model_output("del_fm", "delete_a", {"a": 1})
        repo.store_model_output("del_fm", "delete_b", {"b": 2})

        deleted = repo.delete_outputs_for_model("del_fm")
        assert deleted == ["delete_a", "delete_b"]
        results = repo.list_model_outputs("del_fm")
        assert results == []
