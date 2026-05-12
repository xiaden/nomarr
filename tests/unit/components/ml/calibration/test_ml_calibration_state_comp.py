"""Tests for nomarr.components.ml.calibration.ml_calibration_state_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.calibration.ml_calibration_state_comp import (
    clear_all_calibration_data,
    compute_reconciliation_info,
    count_recent_calibration_states,
    create_calibration_history_snapshot,
    delete_calibration_state,
    delete_old_calibration_history_snapshots,
    get_calibration_version,
    get_latest_calibration_history_snapshot,
    get_latest_calibration_state_updated_at,
    load_all_calibration_states,
    load_calibration_state,
    save_calibration_state,
    set_calibration_last_run,
    set_calibration_version,
    update_file_calibration_hash,
    update_file_calibration_hashes_batch,
)
from nomarr.helpers.constants.file_states import STATE_CALIBRATED, STATE_NOT_CALIBRATED


class TestUpdateFileCalibrationHash:
    """Tests for update_file_calibration_hash delegation."""

    @pytest.mark.unit
    def test_delegates_to_file_states_transition(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.ml.calibration.ml_calibration_state_comp.transition_file_state"
        ) as mock_transition:
            update_file_calibration_hash(mock_db, "library_files/abc123")

        mock_transition.assert_called_once_with(
            mock_db,
            ["library_files/abc123"],
            STATE_NOT_CALIBRATED,
            STATE_CALIBRATED,
        )


class TestUpdateFileCalibrationHashesBatch:
    """Tests for update_file_calibration_hashes_batch delegation."""

    @pytest.mark.unit
    def test_calls_transition_for_each_file_id(self) -> None:
        mock_db = MagicMock()
        file_ids = ["library_files/a", "library_files/b", "library_files/c"]
        with patch(
            "nomarr.components.ml.calibration.ml_calibration_state_comp.transition_file_state"
        ) as mock_transition:
            update_file_calibration_hashes_batch(mock_db, file_ids)

        assert mock_transition.call_count == 3
        for fid in file_ids:
            mock_transition.assert_any_call(mock_db, [fid], STATE_NOT_CALIBRATED, STATE_CALIBRATED)

    @pytest.mark.unit
    def test_empty_list_makes_no_calls(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.ml.calibration.ml_calibration_state_comp.transition_file_state"
        ) as mock_transition:
            update_file_calibration_hashes_batch(mock_db, [])

        mock_transition.assert_not_called()


class TestComputeReconciliationInfo:
    """Tests for compute_reconciliation_info."""

    @pytest.mark.unit
    def test_none_global_version_returns_no_reconciliation(self) -> None:
        mock_db = MagicMock()
        result = compute_reconciliation_info(mock_db, None)
        assert result["requires_reconciliation"] is False
        assert result["affected_libraries"] == []

    @pytest.mark.unit
    def test_no_writable_libraries_returns_no_reconciliation(self) -> None:
        mock_db = MagicMock()
        libraries = [
            {"_id": "libraries/1", "file_write_mode": "none"},
            {"_id": "libraries/2", "file_write_mode": "disabled"},
        ]
        with patch(
            "nomarr.components.ml.calibration.ml_calibration_state_comp.list_library_records",
            return_value=libraries,
        ):
            result = compute_reconciliation_info(mock_db, "v1")
        assert result["requires_reconciliation"] is False
        assert result["affected_libraries"] == []

    @pytest.mark.unit
    def test_writable_library_with_outdated_files_returns_affected(self) -> None:
        mock_db = MagicMock()
        libraries = [
            {"_id": "libraries/1", "name": "Music", "file_write_mode": "full"},
        ]
        calibration_status = [
            {"library_id": "libraries/1", "not_calibrated_count": 5},
        ]
        with (
            patch(
                "nomarr.components.ml.calibration.ml_calibration_state_comp.list_library_records",
                return_value=libraries,
            ),
            patch(
                "nomarr.components.ml.calibration.ml_calibration_state_comp.get_calibration_status_by_library",
                return_value=calibration_status,
            ),
        ):
            result = compute_reconciliation_info(mock_db, "v1")
        assert result["requires_reconciliation"] is True
        assert len(result["affected_libraries"]) == 1
        affected = result["affected_libraries"][0]
        assert affected["library_id"] == "libraries/1"
        assert affected["name"] == "Music"
        assert affected["outdated_files"] == 5
        assert affected["file_write_mode"] == "full"

    @pytest.mark.unit
    def test_mix_of_writable_and_nonwritable_filters_correctly(self) -> None:
        mock_db = MagicMock()
        libraries = [
            {"_id": "libraries/1", "name": "Writable", "file_write_mode": "minimal"},
            {"_id": "libraries/2", "name": "ReadOnly", "file_write_mode": "none"},
            {"_id": "libraries/3", "name": "AlsoWritable", "file_write_mode": "full"},
        ]
        calibration_status = [
            {"library_id": "libraries/1", "not_calibrated_count": 3},
            {"library_id": "libraries/2", "not_calibrated_count": 10},
            {"library_id": "libraries/3", "not_calibrated_count": 0},
        ]
        with (
            patch(
                "nomarr.components.ml.calibration.ml_calibration_state_comp.list_library_records",
                return_value=libraries,
            ),
            patch(
                "nomarr.components.ml.calibration.ml_calibration_state_comp.get_calibration_status_by_library",
                return_value=calibration_status,
            ),
        ):
            result = compute_reconciliation_info(mock_db, "v1")
        assert result["requires_reconciliation"] is True
        assert len(result["affected_libraries"]) == 1
        assert result["affected_libraries"][0]["library_id"] == "libraries/1"


class TestCalibrationStateQueries:
    """Tests for constructor-backed calibration_state query helpers."""

    @pytest.mark.unit
    def test_count_recent_uses_updated_at_range_lookup(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_calibration_states.return_value = [
            {"_id": "calibration_state/a", "updated_at": 1_000},
            {"_id": "calibration_state/b", "updated_at": 2_000},
            {"_id": "calibration_state/c", "updated_at": 999},
        ]

        result = count_recent_calibration_states(mock_db, 1_000)

        assert result == 2
        mock_db.ml.list_calibration_states.assert_called_once_with()

    @pytest.mark.unit
    def test_latest_updated_at_returns_max_timestamp(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_calibration_states.return_value = [
            {"updated_at": 1_000},
            {"updated_at": 2_500},
            {"updated_at": 1_750},
        ]

        result = get_latest_calibration_state_updated_at(mock_db)

        assert result == 2_500
        mock_db.ml.list_calibration_states.assert_called_once_with()


class TestCalibrationStateCrud:
    """Tests for constructor-backed calibration state CRUD helpers."""

    @pytest.mark.unit
    def test_save_uses_constructor_upserts_for_state_and_edge(self) -> None:
        mock_db = MagicMock()

        save_calibration_state(
            mock_db,
            model_id="ml_models/model-1",
            head_name="mood_happy",
            label="happy",
            calibration_def_hash="hash-1",
            histogram_spec={"lo": 0.0, "hi": 1.0, "bins": 10, "bin_width": 0.1},
            p5=0.1,
            p95=0.9,
            sample_count=42,
            underflow_count=1,
            overflow_count=2,
            histogram_bins=[{"val": 0.1, "count": 4}],
        )

        mock_db.ml.upsert_calibration_state_doc.assert_called_once()
        mock_db.ml.upsert_model_has_calibration_edge.assert_called_once_with(
            key="mood_happy:happy",
            model_id="ml_models/model-1",
            calibration_state_id="calibration_state/mood_happy:happy",
        )

    @pytest.mark.unit
    def test_load_all_enriches_from_constructor_edge_and_model_lookups(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_calibration_states.return_value = [
            {
                "_id": "calibration_state/mood_happy:happy",
                "_key": "mood_happy:happy",
                "head_name": "mood_happy",
                "label": "happy",
            }
        ]
        mock_db.ml.get_model_has_calibration_edges_by_ids.return_value = [
            {
                "_key": "mood_happy:happy",
                "_from": "ml_models/model-1",
                "_to": "calibration_state/mood_happy:happy",
            }
        ]
        mock_db.ml.get_models_by_ids.return_value = [
            {
                "_id": "ml_models/model-1",
                "backbone": "ast",
                "embedder_release_date": "2026-01-01",
            }
        ]

        result = load_all_calibration_states(mock_db)

        assert result == [
            {
                "_id": "calibration_state/mood_happy:happy",
                "_key": "mood_happy:happy",
                "head_name": "mood_happy",
                "label": "happy",
                "model": {"backbone": "ast", "embedder_release_date": "2026-01-01"},
            }
        ]
        mock_db.ml.get_model_has_calibration_edges_by_ids.assert_called_once_with(
            ["model_has_calibration/mood_happy:happy"]
        )
        mock_db.ml.get_models_by_ids.assert_called_once_with(["ml_models/model-1"])

    @pytest.mark.unit
    def test_delete_removes_edge_and_state_by_constructor_ids(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_calibration_state_doc.return_value = {"_id": "calibration_state/mood_happy:happy"}

        delete_calibration_state(mock_db, "mood_happy", "happy")

        mock_db.ml.delete_model_has_calibration_edge.assert_called_once_with(
            edge_id="model_has_calibration/mood_happy:happy"
        )
        mock_db.ml.delete_calibration_state_doc.assert_called_once_with(
            calibration_id="calibration_state/mood_happy:happy"
        )


class TestClearAllCalibrationData:
    """Tests for clear_all_calibration_data."""

    @pytest.mark.unit
    def test_truncates_collections_and_clears_states(self) -> None:
        mock_db = MagicMock()
        mock_db.app.get_meta.return_value = {"key": "calibration_version", "value": "some_value"}
        with (
            patch(
                "nomarr.components.ml.calibration.ml_calibration_state_comp.bulk_set_not_calibrated",
                return_value=10,
            ) as mock_bulk_set_not_calibrated,
            patch(
                "nomarr.components.ml.calibration.ml_calibration_state_comp.bulk_set_not_vectors_extracted",
            ) as mock_bulk_set_not_vectors_extracted,
        ):
            result = clear_all_calibration_data(mock_db)

        mock_db.ml.truncate_calibration_states.assert_called_once_with()
        mock_db.ml.truncate_calibration_history.assert_called_once_with()
        mock_bulk_set_not_calibrated.assert_called_once_with(mock_db)
        mock_bulk_set_not_vectors_extracted.assert_called_once_with(mock_db)
        assert result["files_updated"] == 10
        assert result["meta_keys_cleared"] == 2

    @pytest.mark.unit
    def test_clears_meta_keys_only_when_present(self) -> None:
        mock_db = MagicMock()
        mock_db.app.get_meta.side_effect = [None, {"key": "calibration_last_run", "value": "exists"}]
        with (
            patch(
                "nomarr.components.ml.calibration.ml_calibration_state_comp.bulk_set_not_calibrated",
                return_value=0,
            ),
            patch("nomarr.components.ml.calibration.ml_calibration_state_comp.bulk_set_not_vectors_extracted"),
        ):
            result = clear_all_calibration_data(mock_db)

        assert result["meta_keys_cleared"] == 1
        mock_db.app.delete_meta.assert_called_once_with(key="calibration_last_run")


class TestLoadCalibrationState:
    """Tests for ``load_calibration_state``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_doc_when_found(self) -> None:
        mock_db = MagicMock()
        expected_doc = {"_id": "calibration_state/mood_happy:happy"}
        mock_db.ml.get_calibration_state_doc.return_value = expected_doc

        result = load_calibration_state(mock_db, "mood_happy", "happy")

        assert result == expected_doc
        mock_db.ml.get_calibration_state_doc.assert_called_once_with("mood_happy", "happy")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_calibration_state_doc.return_value = None

        result = load_calibration_state(mock_db, "mood_happy", "happy")

        assert result is None
        mock_db.ml.get_calibration_state_doc.assert_called_once_with("mood_happy", "happy")


class TestCreateCalibrationHistorySnapshot:
    """Tests for ``create_calibration_history_snapshot``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_inserts_snapshot_and_returns_id(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.add_calibration_history.return_value = "calibration_history/123"

        with patch(
            "nomarr.components.ml.calibration.ml_calibration_state_comp.now_ms",
            return_value=MagicMock(value=123_456),
        ):
            result = create_calibration_history_snapshot(
                mock_db,
                calibration_key="mood_happy:happy",
                p5=0.1,
                p95=0.9,
                sample_count=100,
                underflow_count=2,
                overflow_count=3,
                p5_delta=0.01,
                p95_delta=0.02,
                n_delta=10,
            )

        assert result == "calibration_history/123"
        inserted_doc = mock_db.ml.add_calibration_history.call_args.kwargs["payload"]
        assert inserted_doc == {
            "calibration_key": "mood_happy:happy",
            "snapshot_at": 123_456,
            "p5": 0.1,
            "p95": 0.9,
            "n": 100,
            "underflow_count": 2,
            "overflow_count": 3,
            "p5_delta": 0.01,
            "p95_delta": 0.02,
            "n_delta": 10,
        }


class TestGetLatestCalibrationHistorySnapshot:
    """Tests for ``get_latest_calibration_history_snapshot``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_no_snapshots(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_calibration_history_snapshots.return_value = []

        result = get_latest_calibration_history_snapshot(mock_db, "mood_happy:happy")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_snapshot_with_highest_snapshot_at(self) -> None:
        mock_db = MagicMock()
        older = {"_id": "calibration_history/1", "snapshot_at": 10}
        newer = {"_id": "calibration_history/2", "snapshot_at": 20}
        mock_db.ml.get_calibration_history_snapshots.return_value = [older, newer]

        result = get_latest_calibration_history_snapshot(mock_db, "mood_happy:happy")

        assert result == newer
        mock_db.ml.get_calibration_history_snapshots.assert_called_once_with(calibration_key="mood_happy:happy")


class TestDeleteOldCalibrationHistorySnapshots:
    """Tests for ``delete_old_calibration_history_snapshots``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_count_within_limit(self) -> None:
        mock_db = MagicMock()
        snapshots = [{"_id": f"calibration_history/{index}", "snapshot_at": index} for index in range(5)]
        mock_db.ml.get_calibration_history_snapshots.return_value = snapshots

        result = delete_old_calibration_history_snapshots(mock_db, "mood_happy:happy", keep_count=10)

        assert result == 0
        mock_db.ml.delete_calibration_history_entries.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_oldest_snapshots_beyond_limit(self) -> None:
        mock_db = MagicMock()
        snapshots = [
            {"_id": "calibration_history/a", "snapshot_at": 10},
            {"_id": "calibration_history/b", "snapshot_at": 50},
            {"_id": "calibration_history/c", "snapshot_at": 30},
            {"_id": "calibration_history/d", "snapshot_at": 40},
            {"_id": "calibration_history/e", "snapshot_at": 20},
        ]
        mock_db.ml.get_calibration_history_snapshots.return_value = snapshots

        result = delete_old_calibration_history_snapshots(mock_db, "mood_happy:happy", keep_count=3)

        assert result == 2
        mock_db.ml.delete_calibration_history_entries.assert_called_once_with(
            entry_ids=["calibration_history/e", "calibration_history/a"]
        )


class TestCalibrationVersionMeta:
    """Tests for calibration version metadata helpers."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_calibration_version_returns_none_when_doc_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.app.get_meta.return_value = None

        result = get_calibration_version(mock_db)

        assert result is None
        mock_db.app.get_meta.assert_called_once_with(key="calibration_version")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_calibration_version_returns_value_from_doc(self) -> None:
        mock_db = MagicMock()
        mock_db.app.get_meta.return_value = {"key": "calibration_version", "value": "hash-123"}

        result = get_calibration_version(mock_db)

        assert result == "hash-123"
        mock_db.app.get_meta.assert_called_once_with(key="calibration_version")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_set_calibration_version_delegates_to_upsert(self) -> None:
        mock_db = MagicMock()

        set_calibration_version(mock_db, "hash-123")

        mock_db.app.upsert_meta.assert_called_once_with(key="calibration_version", payload={"value": "hash-123"})

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_set_calibration_last_run_delegates_to_upsert(self) -> None:
        mock_db = MagicMock()

        set_calibration_last_run(mock_db, "2026-04-13T12:00:00Z")

        mock_db.app.upsert_meta.assert_called_once_with(
            key="calibration_last_run", payload={"value": "2026-04-13T12:00:00Z"}
        )
