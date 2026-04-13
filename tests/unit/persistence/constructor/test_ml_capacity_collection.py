"""Tests for constructor-backed access to the ml_capacity collection."""

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
def ml_capacity_namespace(mock_db: MagicMock):
    """Provide the constructor-backed ml_capacity namespace."""
    return SchemaConstructor(mock_db).build_collection_namespace("ml_capacity", SCHEMA["ml_capacity"])


class TestMlCapacityCollection:
    """Migration-coverage tests for the ml_capacity constructor namespace."""

    @pytest.mark.unit
    def test_model_set_hash_lookup_uses_physical_collection_alias(self, ml_capacity_namespace, mock_db) -> None:
        """`model_set_hash.get()` should target the physical ml_capacity_estimates collection."""
        mock_db.aql.execute.return_value = iter(
            [{"model_set_hash": "abc123", "measured_backbone_vram_mb": 8000}],
        )

        result = ml_capacity_namespace.model_set_hash.get("abc123")

        assert result == {"model_set_hash": "abc123", "measured_backbone_vram_mb": 8000}
        assert mock_db.aql.execute.call_args.kwargs["bind_vars"]["@col"] == "ml_capacity_estimates"

    @pytest.mark.unit
    def test_model_set_hash_upsert_accepts_estimate_payload(self, ml_capacity_namespace, mock_db) -> None:
        """`model_set_hash.upsert()` replaces the old save_capacity_estimate helper."""
        mock_db.aql.execute.return_value = iter(["ml_capacity_estimates/1"])

        result = ml_capacity_namespace.model_set_hash.upsert(
            [{"model_set_hash": "abc123", "estimated_worker_ram_mb": 2048}],
            match_field="model_set_hash",
        )

        assert result == ["ml_capacity_estimates/1"]

    @pytest.mark.unit
    def test_model_set_hash_delete_returns_deleted_count(self, ml_capacity_namespace, mock_db) -> None:
        """`model_set_hash.delete()` replaces the old delete helper."""
        mock_db.aql.execute.return_value = iter([1])

        assert ml_capacity_namespace.model_set_hash.delete("abc123") == 1
