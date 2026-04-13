"""Tests for constructor-backed access to the worker_claims collection."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.constructor import SchemaConstructor
from nomarr.persistence.schema import SCHEMA


@pytest.fixture
def mock_db() -> MagicMock:
    """Provide a mock Arango database handle for constructor tests."""
    return MagicMock()


@pytest.fixture
def worker_claims_namespace(mock_db: MagicMock):
    """Provide the constructor-backed worker_claims namespace."""
    return SchemaConstructor(mock_db).build_collection_namespace("worker_claims", SCHEMA["worker_claims"])


class TestWorkerClaimsCollection:
    """Migration-coverage tests for the worker_claims constructor namespace."""

    @pytest.mark.unit
    def test_file_id_lookup_returns_single_claim(self, worker_claims_namespace, mock_db) -> None:
        """`file_id.get()` replaces the old get_claim helper."""
        mock_db.aql.execute.return_value = iter(
            [{"file_id": "library_files/abc", "worker_id": "worker:tag:0", "claimed_at": 12345}],
        )

        assert worker_claims_namespace.file_id.get("library_files/abc") == {
            "file_id": "library_files/abc",
            "worker_id": "worker:tag:0",
            "claimed_at": 12345,
        }

    @pytest.mark.unit
    def test_worker_lookup_returns_claims_for_worker(self, worker_claims_namespace, mock_db) -> None:
        """`worker_id.get()` replaces the per-worker claim list helper."""
        mock_db.aql.execute.return_value = iter(
            [{"file_id": "library_files/abc", "worker_id": "worker:tag:0"}],
        )

        assert worker_claims_namespace.worker_id.get.many("worker:tag:0", limit=10) == [
            {"file_id": "library_files/abc", "worker_id": "worker:tag:0"},
        ]

    @pytest.mark.unit
    def test_worker_delete_returns_deleted_count(self, worker_claims_namespace, mock_db) -> None:
        """`worker_id.delete()` supports bulk release for one worker."""
        mock_db.aql.execute.return_value = iter([1, 1, 1])

        assert worker_claims_namespace.worker_id.delete("worker:tag:0") == 3
