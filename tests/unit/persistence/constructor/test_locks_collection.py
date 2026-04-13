"""Tests for constructor-backed access to the locks collection."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.constructor import SchemaConstructor
from nomarr.persistence.schema import SCHEMA, Op


@pytest.fixture
def mock_db() -> MagicMock:
    """Provide a mock Arango database handle for constructor tests."""
    return MagicMock()


@pytest.fixture
def locks_namespace(mock_db: MagicMock):
    """Provide the constructor-backed locks namespace."""
    return SchemaConstructor(mock_db).build_collection_namespace("locks", SCHEMA["locks"])


class TestLocksCollection:
    """Migration-coverage tests for the locks constructor namespace."""

    @pytest.mark.unit
    def test_document_reference_lookup_returns_lock_doc(self, locks_namespace, mock_db) -> None:
        """`document_reference.get()` replaces the old get_lock_status helper."""
        mock_db.aql.execute.return_value = iter(
            [{"document_reference": "vector_promotion:effnet__lib1", "holder": "worker:tag:0"}],
        )

        assert locks_namespace.document_reference.get("vector_promotion:effnet__lib1") == {
            "document_reference": "vector_promotion:effnet__lib1",
            "holder": "worker:tag:0",
        }

    @pytest.mark.unit
    def test_expiry_filter_supports_expired_lock_scan(self, locks_namespace, mock_db) -> None:
        """`expires_at.get.in_()` replaces expiry-based lock cleanup queries."""
        mock_db.aql.execute.return_value = iter(
            [{"document_reference": "capacity_probe:abc", "expires_at": 500.0}],
        )

        result = locks_namespace.expires_at.get.in_({Op.LT: 1000.0}, limit=10)

        assert result == [{"document_reference": "capacity_probe:abc", "expires_at": 500.0}]

    @pytest.mark.unit
    def test_upsert_accepts_completion_payload_by_reference(self, locks_namespace, mock_db) -> None:
        """`document_reference.upsert()` is the constructor replacement for complete_lock."""
        mock_db.aql.execute.return_value = iter(["locks/1"])

        result = locks_namespace.document_reference.upsert(
            [{"document_reference": "capacity_probe:abc", "status": "complete"}],
            match_field="document_reference",
        )

        assert result == ["locks/1"]
