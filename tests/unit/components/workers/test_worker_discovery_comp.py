"""Tests for nomarr.components.workers.worker_discovery_comp module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.workers.worker_discovery_comp import (
    claim_file,
    cleanup_stale_claims,
    discover_next_file,
    release_claims_for_worker,
)
from nomarr.helpers.exceptions import DuplicateEntityError


class TestDiscoverNextFile:
    """Tests for discover_next_file."""

    @pytest.mark.unit
    def test_returns_file_id_when_file_found(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.workers.worker_discovery_comp.discover_next_untagged_file",
            return_value={"id": 123},
        ) as mock_discover_next:
            result = discover_next_file(mock_db)

        assert result == "123"
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
    def _duplicate_claim_error() -> DuplicateEntityError:
        """Build a duplicate entity error for the claim path."""
        return DuplicateEntityError()

    @pytest.mark.unit
    def test_returns_true_on_success(self) -> None:
        mock_db = MagicMock()
        result = claim_file(mock_db, "123", "worker:tag:0")
        assert result is True
        mock_db.app.add_claim.assert_called_once()
        inserted = mock_db.app.add_claim.call_args.args[0]
        assert inserted["key"] == "claim_123"
        assert inserted["file_id"] == "123"
        assert inserted["worker_id"] == "worker:tag:0"

    @pytest.mark.unit
    def test_returns_false_when_duplicate_insert_raises(self) -> None:
        mock_db = MagicMock()
        mock_db.app.add_claim.side_effect = self._duplicate_claim_error()

        result = claim_file(mock_db, f"{'songs'}/abc", "worker:tag:0")

        assert result is False
        mock_db.app.add_claim.assert_called_once()

    @pytest.mark.unit
    def test_returns_false_when_already_claimed(self) -> None:
        mock_db = MagicMock()
        mock_db.app.add_claim.side_effect = self._duplicate_claim_error()
        result = claim_file(mock_db, "456", "worker:tag:1")
        assert result is False
        mock_db.app.add_claim.assert_called_once()


class TestCleanupStaleClaims:
    """Tests for cleanup_stale_claims."""

    @pytest.mark.unit
    def test_bulk_fetches_claims_and_groups_deletes(self) -> None:
        mock_db = MagicMock()
        mock_db.app.list_claims.return_value = [
            {
                "_id": "worker_claims/claim1",
                "worker_id": "worker:stale",
                "file_id": 1,
            },
            {
                "_id": "worker_claims/claim2",
                "worker_id": "worker:active",
                "file_id": 2,
            },
            {
                "_id": "worker_claims/claim3",
                "worker_id": "worker:active",
                "file_id": 3,
            },
            {
                "_id": "worker_claims/claim4",
                "worker_id": "worker:active",
                "file_id": 4,
                "claim_type": "reconcile",
            },
        ]
        mock_db.app.list_worker_health.return_value = [
            {"component_id": "worker:active", "last_heartbeat": 9001},
        ]
        mock_db.library.list_files_by_ids.return_value = [
            {"id": 3},
        ]
        mock_db.app.list_file_docs_in_state.return_value = [
            {"id": 3},
            {"id": 999},
        ]
        mock_db.app.remove_claims.side_effect = [1, 2]

        with patch(
            "nomarr.components.workers.worker_discovery_comp.now_ms",
            return_value=SimpleNamespace(value=10000),
        ):
            result = cleanup_stale_claims(mock_db, heartbeat_timeout_ms=1000)

        assert result == 3
        mock_db.app.list_claims.assert_called_once_with()
        mock_db.app.list_worker_health.assert_called_once_with()
        mock_db.library.list_files_by_ids.assert_called_once_with([2, 3])
        mock_db.app.list_file_docs_in_state.assert_called_once_with("tagged")
        assert mock_db.app.remove_claims.call_args_list == [
            call(worker_ids=["worker:stale"]),
            call(
                file_ids=[
                    2,
                    3,
                ]
            ),
        ]

    @pytest.mark.unit
    def test_returns_zero_without_claims(self) -> None:
        mock_db = MagicMock()
        mock_db.app.list_claims.return_value = []

        result = cleanup_stale_claims(mock_db, heartbeat_timeout_ms=1000)

        assert result == 0
        mock_db.app.list_claims.assert_called_once_with()
        mock_db.app.list_worker_health.assert_not_called()
        mock_db.library.list_files_by_ids.assert_not_called()
        mock_db.app.list_file_docs_in_state.assert_not_called()
        mock_db.app.remove_claims.assert_not_called()


class TestReleaseClaimsForWorker:
    """Tests for release_claims_for_worker."""

    @pytest.mark.unit
    def test_returns_file_ids_with_single_bulk_read_and_delete(self) -> None:
        mock_db = MagicMock()
        mock_db.app.list_claims.return_value = [
            {
                "_id": "worker_claims/claim1",
                "worker_id": "worker:tag:0",
                "file_id": f"{'songs'}/file1",
            },
            {
                "_id": "worker_claims/claim2",
                "worker_id": "worker:tag:0",
                "file_id": f"{'songs'}/file2",
            },
        ]

        result = release_claims_for_worker(mock_db, "worker:tag:0")

        assert result == [
            f"{'songs'}/file1",
            f"{'songs'}/file2",
        ]
        mock_db.app.list_claims.assert_called_once_with()
        mock_db.app.remove_claims.assert_called_once_with(worker_ids=["worker:tag:0"])

    @pytest.mark.unit
    def test_returns_empty_list_without_claims(self) -> None:
        mock_db = MagicMock()
        mock_db.app.list_claims.return_value = []

        result = release_claims_for_worker(mock_db, "worker:tag:0")

        assert result == []
        mock_db.app.list_claims.assert_called_once_with()
        mock_db.app.remove_claims.assert_not_called()
