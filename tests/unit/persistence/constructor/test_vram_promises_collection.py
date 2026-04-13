"""Tests for constructor-backed access to the vram_promises collection."""

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
def vram_promises_namespace(mock_db: MagicMock):
    """Provide the constructor-backed vram_promises namespace."""
    return SchemaConstructor(mock_db).build_collection_namespace("vram_promises", SCHEMA["vram_promises"])


class TestVramPromisesCollection:
    """Migration-coverage tests for the vram_promises constructor namespace."""

    @pytest.mark.unit
    def test_worker_lookup_returns_worker_promises(self, vram_promises_namespace, mock_db) -> None:
        """`worker_id.get()` replaces per-worker promise scans."""
        mock_db.aql.execute.return_value = iter(
            [{"worker_id": "worker:tag:0", "model_path": "/models/a.onnx", "promised_mb": 512.0}],
        )

        result = vram_promises_namespace.worker_id.get.many("worker:tag:0", limit=5)

        assert result == [{"worker_id": "worker:tag:0", "model_path": "/models/a.onnx", "promised_mb": 512.0}]

    @pytest.mark.unit
    def test_worker_collect_returns_distinct_worker_ids(self, vram_promises_namespace, mock_db) -> None:
        """`worker_id.collect()` supports full-fleet promise reconstruction."""
        mock_db.aql.execute.return_value = iter(["worker:tag:0", "worker:tag:1"])

        assert vram_promises_namespace.worker_id.collect(limit=10) == ["worker:tag:0", "worker:tag:1"]

    @pytest.mark.unit
    def test_model_path_delete_returns_deleted_count(self, vram_promises_namespace, mock_db) -> None:
        """`model_path.delete()` can clear promises for one model path when needed."""
        mock_db.aql.execute.return_value = iter([1, 1])

        assert vram_promises_namespace.model_path.delete("/models/a.onnx") == 2
