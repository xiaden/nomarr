"""Unit tests for CalibrationRepo."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from nomarr.persistence.database.calibration_repo import CalibrationRepo
from nomarr.persistence.models.ml_model import MlModel


def _insert_model(session, model_id: str = "cal_model") -> str:
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
class TestCalibrationRepo:
    """Tests for CalibrationRepo CRUD and query methods."""

    def test_set_state_insert(self, pg_session) -> None:
        """set_state should insert a new calibration state."""
        _insert_model(pg_session, "cs_model_1")
        repo = CalibrationRepo(pg_session)
        record = repo.set_state("cs_model_1", {"threshold": 0.8})
        assert record["id"] > 0
        assert record["model_id"] == "cs_model_1"
        assert record["state_data"]["threshold"] == 0.8
        assert record["updated_at"] > 0

    def test_set_state_update(self, pg_session) -> None:
        """set_state should update an existing calibration state."""
        _insert_model(pg_session, "cs_model_2")
        repo = CalibrationRepo(pg_session)
        repo.set_state("cs_model_2", {"threshold": 0.5})
        updated = repo.set_state("cs_model_2", {"threshold": 0.9})
        assert updated["model_id"] == "cs_model_2"
        assert updated["state_data"]["threshold"] == 0.9

    def test_get_state_existing(self, pg_session) -> None:
        """get_state should return the state for an existing model."""
        _insert_model(pg_session, "gs_model")
        repo = CalibrationRepo(pg_session)
        repo.set_state("gs_model", {"status": "done"})
        result = repo.get_state("gs_model")
        assert result is not None
        assert result["model_id"] == "gs_model"
        assert result["state_data"]["status"] == "done"

    def test_get_state_nonexistent(self, pg_session) -> None:
        """get_state should return None for a model with no state."""
        repo = CalibrationRepo(pg_session)
        result = repo.get_state("no_such_model")
        assert result is None

    def test_list_states(self, pg_session) -> None:
        """list_states should return all calibration state rows."""
        _insert_model(pg_session, "ls_model_1")
        _insert_model(pg_session, "ls_model_2")
        repo = CalibrationRepo(pg_session)
        repo.set_state("ls_model_1", {"a": 1})
        repo.set_state("ls_model_2", {"b": 2})

        results = repo.list_states()
        model_ids = {r["model_id"] for r in results}
        assert "ls_model_1" in model_ids
        assert "ls_model_2" in model_ids

    def test_list_states_with_models(self, pg_session) -> None:
        """list_states_with_models should join with ml_models for backbone_id."""
        _insert_model(pg_session, "lsm_model")
        repo = CalibrationRepo(pg_session)
        repo.set_state("lsm_model", {"status": "ok"})

        results = repo.list_states_with_models()
        assert len(results) >= 1
        matching = [r for r in results if r["model_id"] == "lsm_model"]
        assert len(matching) == 1
        assert matching[0]["backbone_id"] == "bb_1"
        assert matching[0]["state_data"]["status"] == "ok"

    def test_delete_state(self, pg_session) -> None:
        """delete_state should remove a state by its natural (model, head, label) identity."""
        _insert_model(pg_session, "ds_model")
        repo = CalibrationRepo(pg_session)
        record = repo.set_state("ds_model", {"head_name": "head", "label": "pop", "x": 1})
        repo.delete_state(record["model_id"], record["state_data"]["head_name"], record["state_data"]["label"])
        result = repo.get_state("ds_model")
        assert result is None

    def test_delete_state_3part_identity_removes_only_matching_row(self, pg_session) -> None:
        """delete_state should delete only the row matching the full (model, head, label) identity."""
        _insert_model(pg_session, "ds_multi")
        repo = CalibrationRepo(pg_session)
        repo.set_state("ds_multi", {"head_name": "head", "label": "pop", "v": "pop"})
        repo.set_state("ds_multi", {"head_name": "head", "label": "rock", "v": "rock"})

        repo.delete_state("ds_multi", "head", "pop")

        remaining = repo.list_states_for_model("ds_multi")
        assert len(remaining) == 1
        assert remaining[0]["state_data"]["label"] == "rock"

    def test_set_state_update_3part_identity_only_updates_matching_row(self, pg_session) -> None:
        """set_state should update only the row matching the full (model, head, label) identity."""
        _insert_model(pg_session, "us_multi")
        repo = CalibrationRepo(pg_session)
        repo.set_state("us_multi", {"head_name": "head", "label": "pop", "v": 1})
        repo.set_state("us_multi", {"head_name": "head", "label": "rock", "v": 2})

        updated = repo.set_state("us_multi", {"head_name": "head", "label": "pop", "v": 99})
        assert updated["state_data"]["v"] == 99
        assert updated["state_data"]["label"] == "pop"

        other = repo.get_state_by_identity("us_multi", "head", "rock")
        assert other is not None
        assert other["state_data"]["v"] == 2  # untouched

    def test_list_states_for_model_scoping(self, pg_session) -> None:
        """list_states_for_model should scope by model, and optionally by head/label."""
        _insert_model(pg_session, "lsfm_model")
        repo = CalibrationRepo(pg_session)
        repo.set_state("lsfm_model", {"head_name": "head", "label": "pop", "v": 1})
        repo.set_state("lsfm_model", {"head_name": "head", "label": "rock", "v": 2})
        repo.set_state("lsfm_model", {"head_name": "other", "label": "jazz", "v": 3})

        # No filter: all heads/labels for the model.
        assert len(repo.list_states_for_model("lsfm_model")) == 3
        # Head-only filter.
        head_only = repo.list_states_for_model("lsfm_model", head_name="head")
        assert {r["state_data"]["label"] for r in head_only} == {"pop", "rock"}
        # Label-only filter.
        label_only = repo.list_states_for_model("lsfm_model", label="rock")
        assert len(label_only) == 1
        assert label_only[0]["state_data"]["head_name"] == "head"
        # Both filters: exact identity.
        assert len(repo.list_states_for_model("lsfm_model", head_name="head", label="pop")) == 1
        # Non-matching combo.
        assert repo.list_states_for_model("lsfm_model", head_name="head", label="jazz") == []

    def test_list_states_with_models_returns_typed_joined_result(self, pg_session) -> None:
        """list_states_with_models should return CalibrationStateJoined rows, not raw dicts."""
        from nomarr.helpers.dto.calibration_repo_dto import CalibrationStateJoined

        _insert_model(pg_session, "lsmw_model")
        repo = CalibrationRepo(pg_session)
        repo.set_state("lsmw_model", {"head_name": "head", "label": "pop", "status": "ok"})

        results = repo.list_states_with_models()
        matching = [r for r in results if r["model_id"] == "lsmw_model"]
        assert len(matching) == 1
        row = matching[0]
        assert isinstance(row, CalibrationStateJoined)
        assert row["backbone_id"] == "bb_1"
        assert row["state_data"]["status"] == "ok"
        # RegisteredModel metadata present for Plan C construction.
        assert row["model_type"] == "genre"
        assert "path" in row
        assert "head_release_date" in row

    def test_count_calibration_history_database_side(self, pg_session) -> None:
        """count_calibration_history should return the database-side COUNT for one identity."""
        _insert_model(pg_session, "count_model")
        repo = CalibrationRepo(pg_session)
        assert repo.count_calibration_history("count_model", "head", "pop") == 0
        repo.add_calibration_history_snapshot("count_model", "head", "pop", 1000, {"p5": 0.1, "p95": 0.9})
        repo.add_calibration_history_snapshot("count_model", "head", "pop", 2000, {"p5": 0.2, "p95": 0.8})
        repo.add_calibration_history_snapshot("count_model", "head", "rock", 3000, {"p5": 0.3, "p95": 0.7})
        # Scoped to head/label identity, not model-wide.
        assert repo.count_calibration_history("count_model", "head", "pop") == 2
        assert repo.count_calibration_history("count_model", "head", "rock") == 1

    def test_remove_calibration_history_retention(self, pg_session) -> None:
        """remove_calibration_history should retain the NEWEST keep_count and return #removed."""
        _insert_model(pg_session, "ret_model")
        repo = CalibrationRepo(pg_session)
        for i in range(5):
            repo.add_calibration_history_snapshot("ret_model", "head", "pop", 1000 + i, {"seq": i})
        # keep newest 2 of 5 -> 3 removed.
        removed = repo.remove_calibration_history("ret_model", "head", "pop", keep_count=2)
        assert removed == 3
        remaining = repo.list_calibration_history("ret_model", "head", "pop")
        assert len(remaining) == 2
        # Newest first.
        assert [r["created_at"] for r in remaining] == [1004, 1003]

    def test_remove_calibration_history_zero_deletes_all(self, pg_session) -> None:
        """remove_calibration_history with keep_count=0 should delete all rows for the identity."""
        _insert_model(pg_session, "ret0_model")
        repo = CalibrationRepo(pg_session)
        repo.add_calibration_history_snapshot("ret0_model", "head", "pop", 1000, {"p5": 0.1})
        repo.add_calibration_history_snapshot("ret0_model", "head", "pop", 2000, {"p5": 0.2})
        removed = repo.remove_calibration_history("ret0_model", "head", "pop", keep_count=0)
        assert removed == 2
        assert repo.count_calibration_history("ret0_model", "head", "pop") == 0

    def test_remove_calibration_history_negative_raises(self, pg_session) -> None:
        """remove_calibration_history with a negative keep_count should raise ValueError."""
        _insert_model(pg_session, "retneg_model")
        repo = CalibrationRepo(pg_session)
        with pytest.raises(ValueError):
            repo.remove_calibration_history("retneg_model", "head", "pop", keep_count=-1)

    def test_history_snapshot_round_trip_with_output_id(self, pg_session) -> None:
        """add/list/latest should round-trip envelope-carried output_id under head/label scoping."""
        _insert_model(pg_session, "hist_rt")
        repo = CalibrationRepo(pg_session)
        metrics = {
            "p5": 0.1,
            "p95": 0.9,
            "sample_count": 10,
            "underflow_count": 1,
            "overflow_count": 2,
            "output_id": "deadbeef12345678",
        }
        repo.add_calibration_history_snapshot("hist_rt", "head", "pop", 1000, metrics)
        repo.add_calibration_history_snapshot("hist_rt", "head", "rock", 2000, metrics)

        latest = repo.get_latest_calibration_history_snapshot("hist_rt", "head", "pop")
        assert latest is not None
        assert latest["data"]["output_id"] == "deadbeef12345678"
        assert latest["data"]["head_name"] == "head"
        assert latest["data"]["label"] == "pop"
        assert latest["created_at"] == 1000

        all_pop = repo.list_calibration_history("hist_rt", "head", "pop")
        assert len(all_pop) == 1
        assert all_pop[0]["data"]["output_id"] == "deadbeef12345678"
        # head/label scoping isolates the identities.
        assert repo.count_calibration_history("hist_rt", "head", "rock") == 1
        rock_latest = repo.get_latest_calibration_history_snapshot("hist_rt", "head", "rock")
        assert rock_latest is not None
        assert rock_latest["created_at"] == 2000

    def test_add_history_snapshot_injects_head_and_label_into_envelope(self, pg_session) -> None:
        """The repo should build the storage envelope and inject head_name/label itself."""
        _insert_model(pg_session, "hist_inj")
        repo = CalibrationRepo(pg_session)
        repo.add_calibration_history_snapshot("hist_inj", "head", "pop", 1000, {"p5": 0.1, "p95": 0.9})
        history = repo.get_history("hist_inj")
        assert len(history) == 1
        assert history[0]["event"] == "calibration_snapshot"
        assert history[0]["data"]["head_name"] == "head"
        assert history[0]["data"]["label"] == "pop"
        assert history[0]["created_at"] == 1000  # snapshot_at -> created_at epoch-ms

    def test_truncate_states(self, pg_session) -> None:
        """truncate_states should remove all calibration state rows."""
        _insert_model(pg_session, "ts_model_1")
        _insert_model(pg_session, "ts_model_2")
        repo = CalibrationRepo(pg_session)
        repo.set_state("ts_model_1", {"a": 1})
        repo.set_state("ts_model_2", {"b": 2})

        repo.truncate_states()
        results = repo.list_states()
        assert results == []

    def test_truncate_history(self, pg_session) -> None:
        """truncate_history should remove all calibration history rows."""
        _insert_model(pg_session, "th_model")
        repo = CalibrationRepo(pg_session)
        repo.record_history("th_model", "e1", {})
        repo.record_history("th_model", "e2", {})

        repo.truncate_history()
        results = repo.get_history("th_model")
        assert results == []
