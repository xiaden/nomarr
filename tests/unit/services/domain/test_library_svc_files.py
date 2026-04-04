"""Tests for nomarr.services.domain.library_svc.files module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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
    def test_retries_all_errored_when_no_file_ids(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.get_errored_file_ids.return_value = [
            "library_files/1",
            "library_files/2",
        ]
        mock_db.file_states.bulk_set_not_errored.return_value = 2
        mixin = _ConcreteFilesMixin(mock_db)
        result = mixin.retry_errored_files("abc123")
        assert result == RetryErroredResult(retried=2)
        mock_db.file_states.bulk_set_not_errored.assert_called_once_with(
            ["library_files/1", "library_files/2"],
        )
        mock_db.file_states.clear_tagged_batch.assert_called_once_with(
            ["library_files/1", "library_files/2"],
        )

    @pytest.mark.unit
    def test_filters_to_specified_file_ids(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.get_errored_file_ids.return_value = [
            "library_files/1",
            "library_files/2",
            "library_files/3",
        ]
        mock_db.file_states.bulk_set_not_errored.return_value = 2
        mixin = _ConcreteFilesMixin(mock_db)
        mixin.retry_errored_files(
            "abc123", file_ids=["library_files/1", "library_files/3"],
        )
        mock_db.file_states.bulk_set_not_errored.assert_called_once_with(
            ["library_files/1", "library_files/3"],
        )
        mock_db.file_states.clear_tagged_batch.assert_called_once_with(
            ["library_files/1", "library_files/3"],
        )

    @pytest.mark.unit
    def test_calls_clear_tagged_batch(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.get_errored_file_ids.return_value = ["library_files/1"]
        mock_db.file_states.bulk_set_not_errored.return_value = 1
        mixin = _ConcreteFilesMixin(mock_db)
        mixin.retry_errored_files("abc123")
        mock_db.file_states.clear_tagged_batch.assert_called_once_with(
            ["library_files/1"],
        )

    @pytest.mark.unit
    def test_raises_on_invalid_library(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteFilesMixin(mock_db)
        mixin._get_library_or_error = MagicMock(side_effect=ValueError("not found"))
        with pytest.raises(ValueError, match="not found"):
            mixin.retry_errored_files("bad_id")
