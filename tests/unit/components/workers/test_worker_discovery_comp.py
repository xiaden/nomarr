"""Tests for nomarr.components.workers.worker_discovery_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from arango.exceptions import DocumentInsertError

from nomarr.components.workers.worker_discovery_comp import claim_file, discover_next_file


class TestDiscoverNextFile:
    """Tests for discover_next_file."""

    @pytest.mark.unit
    def test_returns_file_id_when_file_found(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.workers.worker_discovery_comp.discover_next_untagged_file",
            return_value={"_id": "library_files/abc123"},
        ) as mock_discover_next:
            result = discover_next_file(mock_db)

        assert result == "library_files/abc123"
        mock_discover_next.assert_called_once_with(
            mock_db,
            exclude_claimed=True,
        )

    @pytest.mark.unit
    def test_returns_none_when_no_file(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.workers.worker_discovery_comp.discover_next_untagged_file",
            return_value=None,
        ):
            result = discover_next_file(mock_db)
        assert result is None


class TestClaimFile:
    """Tests for claim_file."""

    @staticmethod
    def _duplicate_claim_error() -> DocumentInsertError:
        """Build a minimal duplicate-insert error for the claim path."""
        return DocumentInsertError(MagicMock(), MagicMock())

    @pytest.mark.unit
    def test_returns_true_on_success(self) -> None:
        mock_db = MagicMock()
        result = claim_file(mock_db, "library_files/abc", "worker:tag:0")
        assert result is True
        mock_db.worker_claims.insert.assert_called_once()
        inserted = mock_db.worker_claims.insert.call_args.args[0][0]
        assert inserted["_key"] == "claim_abc"
        assert inserted["file_id"] == "library_files/abc"
        assert inserted["worker_id"] == "worker:tag:0"

    @pytest.mark.unit
    def test_returns_false_when_duplicate_insert_raises(self) -> None:
        mock_db = MagicMock()
        mock_db.worker_claims.insert.side_effect = self._duplicate_claim_error()

        result = claim_file(mock_db, "library_files/abc", "worker:tag:0")

        assert result is False

    @pytest.mark.unit
    def test_returns_false_when_already_claimed(self) -> None:
        mock_db = MagicMock()
        mock_db.worker_claims.insert.side_effect = self._duplicate_claim_error()
        result = claim_file(mock_db, "library_files/abc", "worker:tag:1")
        assert result is False
