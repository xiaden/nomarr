"""Tests for nomarr.components.ml.calibration.ml_calibration_state_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.calibration.ml_calibration_state_comp import (
    clear_all_calibration_data,
    compute_reconciliation_info,
    update_file_calibration_hash,
    update_file_calibration_hashes_batch,
)


class TestUpdateFileCalibrationHash:
    """Tests for update_file_calibration_hash delegation."""

    @pytest.mark.unit
    def test_delegates_to_file_states_set_calibrated(self) -> None:
        mock_db = MagicMock()
        update_file_calibration_hash(mock_db, "library_files/abc123")
        mock_db.file_states.set_calibrated.assert_called_once_with("library_files/abc123")


class TestUpdateFileCalibrationHashesBatch:
    """Tests for update_file_calibration_hashes_batch delegation."""

    @pytest.mark.unit
    def test_calls_set_calibrated_for_each_file_id(self) -> None:
        mock_db = MagicMock()
        file_ids = ["library_files/a", "library_files/b", "library_files/c"]
        update_file_calibration_hashes_batch(mock_db, file_ids)
        assert mock_db.file_states.set_calibrated.call_count == 3
        for fid in file_ids:
            mock_db.file_states.set_calibrated.assert_any_call(fid)

    @pytest.mark.unit
    def test_empty_list_makes_no_calls(self) -> None:
        mock_db = MagicMock()
        update_file_calibration_hashes_batch(mock_db, [])
        mock_db.file_states.set_calibrated.assert_not_called()


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
        mock_db.libraries.list_libraries.return_value = [
            {"_id": "libraries/1", "file_write_mode": "none"},
            {"_id": "libraries/2", "file_write_mode": "disabled"},
        ]
        result = compute_reconciliation_info(mock_db, "v1")
        assert result["requires_reconciliation"] is False
        assert result["affected_libraries"] == []

    @pytest.mark.unit
    def test_writable_library_with_outdated_files_returns_affected(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.list_libraries.return_value = [
            {"_id": "libraries/1", "name": "Music", "file_write_mode": "full"},
        ]
        mock_db.file_states.get_calibration_status_by_library.return_value = [
            {"library_id": "libraries/1", "not_calibrated_count": 5},
        ]
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
        mock_db.libraries.list_libraries.return_value = [
            {"_id": "libraries/1", "name": "Writable", "file_write_mode": "minimal"},
            {"_id": "libraries/2", "name": "ReadOnly", "file_write_mode": "none"},
            {"_id": "libraries/3", "name": "AlsoWritable", "file_write_mode": "full"},
        ]
        mock_db.file_states.get_calibration_status_by_library.return_value = [
            {"library_id": "libraries/1", "not_calibrated_count": 3},
            {"library_id": "libraries/2", "not_calibrated_count": 10},
            {"library_id": "libraries/3", "not_calibrated_count": 0},
        ]
        result = compute_reconciliation_info(mock_db, "v1")
        assert result["requires_reconciliation"] is True
        assert len(result["affected_libraries"]) == 1
        assert result["affected_libraries"][0]["library_id"] == "libraries/1"


class TestClearAllCalibrationData:
    """Tests for clear_all_calibration_data."""

    @pytest.mark.unit
    def test_truncates_collections_and_clears_states(self) -> None:
        mock_db = MagicMock()
        mock_db.meta.get.return_value = "some_value"
        mock_db.file_states.bulk_set_not_calibrated.return_value = 10

        result = clear_all_calibration_data(mock_db)

        mock_db.calibration_state.truncate.assert_called_once()
        mock_db.calibration_history.truncate.assert_called_once()
        mock_db.file_states.bulk_set_not_calibrated.assert_called_once()
        mock_db.file_states.bulk_set_not_vectors_extracted.assert_called_once()
        assert result["files_updated"] == 10
        assert result["meta_keys_cleared"] == 2

    @pytest.mark.unit
    def test_clears_meta_keys_only_when_present(self) -> None:
        mock_db = MagicMock()
        mock_db.meta.get.side_effect = [None, "exists"]
        mock_db.file_states.bulk_set_not_calibrated.return_value = 0

        result = clear_all_calibration_data(mock_db)

        assert result["meta_keys_cleared"] == 1
        mock_db.meta.delete.assert_called_once_with("calibration_last_run")
