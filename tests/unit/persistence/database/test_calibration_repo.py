"""Unit tests for CalibrationRepo."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from nomarr.persistence.database.calibration_repo import CalibrationRepo
from nomarr.persistence.models.ml_model import MlModel


async def _insert_model(session, model_id: str = "cal_model") -> str:
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
class TestCalibrationRepo:
    """Tests for CalibrationRepo CRUD and query methods."""

    @pytest.mark.asyncio
    async def test_set_state_insert(self, pg_session) -> None:
        """set_state should insert a new calibration state."""
        await _insert_model(pg_session, "cs_model_1")
        repo = CalibrationRepo(pg_session)
        record = await repo.set_state("cs_model_1", {"threshold": 0.8})
        assert record["id"] > 0
        assert record["model_id"] == "cs_model_1"
        assert record["state_data"]["threshold"] == 0.8
        assert record["updated_at"] > 0

    @pytest.mark.asyncio
    async def test_set_state_update(self, pg_session) -> None:
        """set_state should update an existing calibration state."""
        await _insert_model(pg_session, "cs_model_2")
        repo = CalibrationRepo(pg_session)
        await repo.set_state("cs_model_2", {"threshold": 0.5})
        updated = await repo.set_state("cs_model_2", {"threshold": 0.9})
        assert updated["model_id"] == "cs_model_2"
        assert updated["state_data"]["threshold"] == 0.9

    @pytest.mark.asyncio
    async def test_get_state_existing(self, pg_session) -> None:
        """get_state should return the state for an existing model."""
        await _insert_model(pg_session, "gs_model")
        repo = CalibrationRepo(pg_session)
        await repo.set_state("gs_model", {"status": "done"})
        result = await repo.get_state("gs_model")
        assert result is not None
        assert result["model_id"] == "gs_model"
        assert result["state_data"]["status"] == "done"

    @pytest.mark.asyncio
    async def test_get_state_nonexistent(self, pg_session) -> None:
        """get_state should return None for a model with no state."""
        repo = CalibrationRepo(pg_session)
        result = await repo.get_state("no_such_model")
        assert result is None

    @pytest.mark.asyncio
    async def test_record_history(self, pg_session) -> None:
        """record_history should insert and return a history record."""
        await _insert_model(pg_session, "hist_model")
        repo = CalibrationRepo(pg_session)
        record = await repo.record_history("hist_model", "calibration_started", {"iterations": 100})
        assert record["id"] > 0
        assert record["model_id"] == "hist_model"
        assert record["event"] == "calibration_started"
        assert record["data"]["iterations"] == 100
        assert record["created_at"] > 0

    @pytest.mark.asyncio
    async def test_get_history(self, pg_session) -> None:
        """get_history should return history records ordered by created_at desc."""
        await _insert_model(pg_session, "gh_model")
        repo = CalibrationRepo(pg_session)
        await repo.record_history("gh_model", "event_1", {"seq": 1})
        await repo.record_history("gh_model", "event_2", {"seq": 2})

        results = await repo.get_history("gh_model")
        assert len(results) == 2
        # Verify both records are present
        events = {r["event"] for r in results}
        assert events == {"event_1", "event_2"}
        # Verify ordering is by created_at desc (if timestamps differ)
        if results[0]["created_at"] != results[1]["created_at"]:
            assert results[0]["created_at"] >= results[1]["created_at"]

    @pytest.mark.asyncio
    async def test_list_states(self, pg_session) -> None:
        """list_states should return all calibration state rows."""
        await _insert_model(pg_session, "ls_model_1")
        await _insert_model(pg_session, "ls_model_2")
        repo = CalibrationRepo(pg_session)
        await repo.set_state("ls_model_1", {"a": 1})
        await repo.set_state("ls_model_2", {"b": 2})

        results = await repo.list_states()
        model_ids = {r["model_id"] for r in results}
        assert "ls_model_1" in model_ids
        assert "ls_model_2" in model_ids

    @pytest.mark.asyncio
    async def test_list_states_with_models(self, pg_session) -> None:
        """list_states_with_models should join with ml_models for backbone_id."""
        await _insert_model(pg_session, "lsm_model")
        repo = CalibrationRepo(pg_session)
        await repo.set_state("lsm_model", {"status": "ok"})

        results = await repo.list_states_with_models()
        assert len(results) >= 1
        matching = [r for r in results if r["model_id"] == "lsm_model"]
        assert len(matching) == 1
        assert matching[0]["backbone_id"] == "bb_1"
        assert matching[0]["state_data"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_delete_state(self, pg_session) -> None:
        """delete_state should remove a calibration state by its PK."""
        await _insert_model(pg_session, "ds_model")
        repo = CalibrationRepo(pg_session)
        record = await repo.set_state("ds_model", {"x": 1})
        await repo.delete_state(record["id"])
        result = await repo.get_state("ds_model")
        assert result is None

    @pytest.mark.asyncio
    async def test_truncate_states(self, pg_session) -> None:
        """truncate_states should remove all calibration state rows."""
        await _insert_model(pg_session, "ts_model_1")
        await _insert_model(pg_session, "ts_model_2")
        repo = CalibrationRepo(pg_session)
        await repo.set_state("ts_model_1", {"a": 1})
        await repo.set_state("ts_model_2", {"b": 2})

        await repo.truncate_states()
        results = await repo.list_states()
        assert results == []

    @pytest.mark.asyncio
    async def test_truncate_history(self, pg_session) -> None:
        """truncate_history should remove all calibration history rows."""
        await _insert_model(pg_session, "th_model")
        repo = CalibrationRepo(pg_session)
        await repo.record_history("th_model", "e1", {})
        await repo.record_history("th_model", "e2", {})

        await repo.truncate_history()
        results = await repo.get_history("th_model")
        assert results == []
