"""Tests for nomarr.services.domain.library_svc.files module."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_TAGGED,
    STATE_TAGGED,
)
from nomarr.helpers.dto.library_dto import RetryErroredResult
from nomarr.services.domain.library_svc.files import LibraryFilesMixin


class _ConcreteFilesMixin(LibraryFilesMixin):
    """Minimal concrete class for testing the mixin."""

    def __init__(self, db: MagicMock) -> None:
        self.db = db
        self.cfg = MagicMock()


class TestRetryErroredFiles:
    """Tests for retry_errored_files."""

    @pytest.mark.unit
    @patch("nomarr.services.domain.library_svc.files.transition_file_state")
    @patch(
        "nomarr.services.domain.library_svc.files.get_errored_file_ids",
        return_value=["library_files/1", "library_files/2"],
    )
    def test_retries_all_errored_when_no_file_ids(
        self,
        mock_get_errored_file_ids: MagicMock,
        mock_transition_file_state: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        mock_db.library.get_library.return_value = {"_id": "libraries/abc123"}
        mixin = _ConcreteFilesMixin(mock_db)

        result = mixin.retry_errored_files("abc123")

        assert result == RetryErroredResult(retried=2)
        mock_get_errored_file_ids.assert_called_once_with(mock_db, "abc123")
        assert mock_transition_file_state.call_args_list == [
            call(mock_db, ["library_files/1", "library_files/2"], STATE_ERRORED, STATE_NOT_ERRORED),
            call(mock_db, ["library_files/1", "library_files/2"], STATE_TAGGED, STATE_NOT_TAGGED),
        ]

    @pytest.mark.unit
    @patch("nomarr.services.domain.library_svc.files.transition_file_state")
    @patch(
        "nomarr.services.domain.library_svc.files.get_errored_file_ids",
        return_value=["library_files/1", "library_files/2", "library_files/3"],
    )
    def test_filters_to_specified_file_ids(
        self,
        mock_get_errored_file_ids: MagicMock,
        mock_transition_file_state: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        mock_db.library.get_library.return_value = {"_id": "libraries/abc123"}
        mixin = _ConcreteFilesMixin(mock_db)

        mixin.retry_errored_files(
            "abc123",
            file_ids=["library_files/1", "library_files/3"],
        )

        mock_get_errored_file_ids.assert_called_once_with(mock_db, "abc123")
        assert mock_transition_file_state.call_args_list == [
            call(mock_db, ["library_files/1", "library_files/3"], STATE_ERRORED, STATE_NOT_ERRORED),
            call(mock_db, ["library_files/1", "library_files/3"], STATE_TAGGED, STATE_NOT_TAGGED),
        ]

    @pytest.mark.unit
    @patch("nomarr.services.domain.library_svc.files.transition_file_state")
    @patch(
        "nomarr.services.domain.library_svc.files.get_errored_file_ids",
        return_value=["library_files/1"],
    )
    def test_calls_transition_helper_twice_for_errored_files(
        self,
        _mock_get_errored_file_ids: MagicMock,
        mock_transition_file_state: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        mock_db.library.get_library.return_value = {"_id": "libraries/abc123"}
        mixin = _ConcreteFilesMixin(mock_db)

        mixin.retry_errored_files("abc123")

        assert mock_transition_file_state.call_count == 2

    @pytest.mark.unit
    def test_raises_on_invalid_library(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteFilesMixin(mock_db)
        with (
            patch.object(mixin, "_get_library_or_error", side_effect=ValueError("not found")),
            pytest.raises(
                ValueError,
                match="not found",
            ),
        ):
            mixin.retry_errored_files("bad_id")


class TestReconcileLibraryPaths:
    """Tests for ``LibraryFilesMixin.reconcile_library_paths``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_workflow_with_expected_arguments(self) -> None:
        """Explicit policy and batch size should be forwarded unchanged."""
        mock_db = MagicMock()
        mixin = _ConcreteFilesMixin(mock_db)
        mixin.cfg.library_root = "/music"
        expected_result = {
            "total_files": 10,
            "valid_files": 8,
            "invalid_config": 1,
            "not_found": 1,
            "unknown_status": 0,
            "deleted_files": 0,
            "errors": 0,
        }

        with patch(
            "nomarr.services.domain.library_svc.files.reconcile_library_paths_workflow",
            return_value=expected_result,
        ) as mock_reconcile_library_paths_workflow:
            result = mixin.reconcile_library_paths(
                "libraries/1",
                policy="delete_invalid",
                batch_size=250,
            )

        assert result is expected_result
        mock_reconcile_library_paths_workflow.assert_called_once_with(
            db=mock_db,
            library_id="libraries/1",
            library_root="/music",
            policy="delete_invalid",
            batch_size=250,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_default_policy_and_batch_size(self) -> None:
        """Omitted args should default to mark_invalid and batch size 1000."""
        mock_db = MagicMock()
        mixin = _ConcreteFilesMixin(mock_db)
        mixin.cfg.library_root = "/music"
        expected_result = {
            "total_files": 0,
            "valid_files": 0,
            "invalid_config": 0,
            "not_found": 0,
            "unknown_status": 0,
            "deleted_files": 0,
            "errors": 0,
        }

        with patch(
            "nomarr.services.domain.library_svc.files.reconcile_library_paths_workflow",
            return_value=expected_result,
        ) as mock_reconcile_library_paths_workflow:
            result = mixin.reconcile_library_paths("libraries/1")

        assert result is expected_result
        mock_reconcile_library_paths_workflow.assert_called_once_with(
            db=mock_db,
            library_id="libraries/1",
            library_root="/music",
            policy="mark_invalid",
            batch_size=1000,
        )
