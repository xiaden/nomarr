"""Tests for nomarr.components.workers.worker_discovery_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.workers.worker_discovery_comp import claim_file, discover_next_file


class TestDiscoverNextFile:
    """Tests for discover_next_file."""

    @pytest.mark.unit
    def test_returns_file_id_when_file_found(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.discover_next_untagged_file.return_value = {
            "_id": "library_files/abc123",
        }
        result = discover_next_file(mock_db)
        assert result == "library_files/abc123"
        mock_db.file_states.discover_next_untagged_file.assert_called_once_with(
            exclude_claimed=True,
        )

    @pytest.mark.unit
    def test_returns_none_when_no_file(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.discover_next_untagged_file.return_value = None
        result = discover_next_file(mock_db)
        assert result is None


class TestClaimFile:
    """Tests for claim_file."""

    @pytest.mark.unit
    def test_returns_true_on_success(self) -> None:
        mock_db = MagicMock()
        mock_db.worker_claims.try_claim_file.return_value = True
        result = claim_file(mock_db, "library_files/abc", "worker:tag:0")
        assert result is True
        mock_db.worker_claims.try_claim_file.assert_called_once_with(
            "library_files/abc", "worker:tag:0",
        )

    @pytest.mark.unit
    def test_returns_false_when_already_claimed(self) -> None:
        mock_db = MagicMock()
        mock_db.worker_claims.try_claim_file.return_value = False
        result = claim_file(mock_db, "library_files/abc", "worker:tag:1")
        assert result is False
