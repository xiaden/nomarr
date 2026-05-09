"""Tests for nomarr.components.workers.worker_discovery_comp module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from arango.exceptions import DocumentInsertError

from nomarr.components.workers.worker_discovery_comp import (
    claim_file,
    cleanup_stale_claims,
    discover_next_file,
    release_claims_for_worker,
)
from nomarr.persistence.query_specs import PaginationSpec, QueryCriterion, QueryOperator, ReadQuerySpec, WriteQuerySpec


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


class TestCleanupStaleClaims:
    """Tests for cleanup_stale_claims."""

    @pytest.mark.unit
    def test_bulk_fetches_claims_and_groups_deletes(self) -> None:
        mock_db = MagicMock()
        mock_db.worker_claims.count.return_value = 4
        mock_db.worker_claims.get.return_value = [
            {"_id": "worker_claims/claim1", "worker_id": "worker:stale", "file_id": "library_files/file1"},
            {"_id": "worker_claims/claim2", "worker_id": "worker:active", "file_id": "library_files/file2"},
            {"_id": "worker_claims/claim3", "worker_id": "worker:active", "file_id": "library_files/file3"},
            {
                "_id": "worker_claims/claim4",
                "worker_id": "worker:active",
                "file_id": "library_files/file4",
                "claim_type": "reconcile",
            },
        ]
        mock_db.health.count.return_value = 1
        mock_db.health.get.return_value = [
            {"component_id": "worker:active", "last_heartbeat": 9001},
        ]
        mock_db.library_files.get.return_value = [
            {"_id": "library_files/file3"},
        ]
        mock_db.file_has_state.get.return_value = [
            {"_from": "library_files/file2", "_to": "file_states/not_tagged"},
            {"_from": "library_files/file3", "_to": "file_states/tagged"},
        ]
        mock_db.worker_claims.delete.side_effect = [1, 2]

        with patch(
            "nomarr.components.workers.worker_discovery_comp.now_ms",
            return_value=SimpleNamespace(value=10000),
        ):
            result = cleanup_stale_claims(mock_db, heartbeat_timeout_ms=1000)

        assert result == 3
        mock_db.worker_claims.aggregate.assert_not_called()
        mock_db.worker_claims.get.assert_called_once_with(
            query_spec=ReadQuerySpec(
                collection_name="worker_claims",
                pagination=PaginationSpec(limit=4),
            )
        )
        mock_db.health.get.assert_called_once_with(
            query_spec=ReadQuerySpec(
                collection_name="health",
                criteria=(QueryCriterion("component_type", QueryOperator.EQ, "worker"),),
                pagination=PaginationSpec(limit=1),
            )
        )
        mock_db.library_files.get.assert_called_once_with(
            query_spec=ReadQuerySpec(
                collection_name="library_files",
                criteria=(QueryCriterion("_id", QueryOperator.IN, ["library_files/file2", "library_files/file3"]),),
                pagination=PaginationSpec(limit=2),
            )
        )
        mock_db.file_has_state.get.assert_called_once_with(
            query_spec=ReadQuerySpec(
                collection_name="file_has_state",
                criteria=(QueryCriterion("_from", QueryOperator.IN, ["library_files/file2", "library_files/file3"]),),
            )
        )
        assert mock_db.worker_claims.delete.call_args_list == [
            call(
                query_spec=WriteQuerySpec(
                    collection_name="worker_claims",
                    criteria=(QueryCriterion("worker_id", QueryOperator.IN, ["worker:stale"]),),
                )
            ),
            call(
                query_spec=WriteQuerySpec(
                    collection_name="worker_claims",
                    criteria=(
                        QueryCriterion("file_id", QueryOperator.IN, ["library_files/file2", "library_files/file3"]),
                    ),
                )
            ),
        ]

    @pytest.mark.unit
    def test_returns_zero_without_claims(self) -> None:
        mock_db = MagicMock()
        mock_db.worker_claims.count.return_value = 0

        result = cleanup_stale_claims(mock_db, heartbeat_timeout_ms=1000)

        assert result == 0
        mock_db.worker_claims.aggregate.assert_not_called()
        mock_db.health.get.assert_not_called()
        mock_db.library_files.get.assert_not_called()
        mock_db.file_has_state.get.assert_not_called()
        mock_db.worker_claims.delete.assert_not_called()


class TestReleaseClaimsForWorker:
    """Tests for release_claims_for_worker."""

    @pytest.mark.unit
    def test_returns_file_ids_with_single_bulk_read_and_delete(self) -> None:
        mock_db = MagicMock()
        mock_db.worker_claims.get.return_value = [
            {"_id": "worker_claims/claim1", "file_id": "library_files/file1"},
            {"_id": "worker_claims/claim2", "file_id": "library_files/file2"},
        ]

        result = release_claims_for_worker(mock_db, "worker:tag:0")

        assert result == ["library_files/file1", "library_files/file2"]
        mock_db.worker_claims.get.assert_called_once_with(
            query_spec=ReadQuerySpec(
                collection_name="worker_claims",
                criteria=(QueryCriterion("worker_id", QueryOperator.EQ, "worker:tag:0"),),
            )
        )
        mock_db.worker_claims.delete.assert_called_once_with(
            query_spec=WriteQuerySpec(
                collection_name="worker_claims",
                criteria=(QueryCriterion("worker_id", QueryOperator.EQ, "worker:tag:0"),),
            )
        )

    @pytest.mark.unit
    def test_returns_empty_list_without_claims(self) -> None:
        mock_db = MagicMock()
        mock_db.worker_claims.get.return_value = []

        result = release_claims_for_worker(mock_db, "worker:tag:0")

        assert result == []
        mock_db.worker_claims.get.assert_called_once_with(
            query_spec=ReadQuerySpec(
                collection_name="worker_claims",
                criteria=(QueryCriterion("worker_id", QueryOperator.EQ, "worker:tag:0"),),
            )
        )
        mock_db.worker_claims.delete.assert_not_called()
