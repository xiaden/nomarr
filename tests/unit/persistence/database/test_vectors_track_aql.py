"""Unit tests for vectors_track_aql runtime schema validation."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.vectors_track_aql import (
    VectorsTrackColdOperations,
    VectorsTrackHotOperations,
    VectorsTrackMaintenanceOperations,
)

_SCHEMA_AWARE_MOCK_PATH = Path(__file__).with_name("schema_aware_mock.py")
_SCHEMA_AWARE_MOCK_SPEC = spec_from_file_location(
    "tests.unit.persistence.database.schema_aware_mock",
    _SCHEMA_AWARE_MOCK_PATH,
)
assert _SCHEMA_AWARE_MOCK_SPEC is not None and _SCHEMA_AWARE_MOCK_SPEC.loader is not None
_SCHEMA_AWARE_MOCK_MODULE = module_from_spec(_SCHEMA_AWARE_MOCK_SPEC)
_SCHEMA_AWARE_MOCK_SPEC.loader.exec_module(_SCHEMA_AWARE_MOCK_MODULE)

SchemaAwareMockDBCtor: type[Any] = _SCHEMA_AWARE_MOCK_MODULE.SchemaAwareMockDB


def _make_schema_mock_db() -> Any:
    """Create a fresh schema-aware mock database instance."""
    return SchemaAwareMockDBCtor()


@pytest.mark.unit
def test_hot_upsert_vector_executes_valid_aql(schema_mock_db: Any) -> None:
    """Hot upsert executes both vector and edge UPSERT statements without schema errors."""
    ops = VectorsTrackHotOperations(schema_mock_db, backbone_id="ast", library_key="lib1")

    ops.upsert_vector(
        file_id="library_files/file1",
        model_suite_hash="abc123def456",
        embed_dim=3,
        vector=[1.0, 2.0, 3.0],
        num_segments=5,
    )

    assert schema_mock_db.aql.execute.call_count == 2


@pytest.mark.unit
def test_hot_delete_by_file_id_executes_valid_aql(schema_mock_db: Any) -> None:
    """Hot delete executes traversal delete and edge cleanup queries without schema errors."""
    ops = VectorsTrackHotOperations(schema_mock_db, backbone_id="ast", library_key="lib1")

    removed = ops.delete_by_file_id("library_files/file1")

    assert removed == 0
    assert schema_mock_db.aql.execute.call_count == 2


@pytest.mark.unit
def test_cold_search_similar_executes_valid_aql(schema_mock_db: Any) -> None:
    """Cold similarity search executes against the dynamic cold collection without schema errors."""
    ops = VectorsTrackColdOperations(schema_mock_db, backbone_id="ast", library_key="lib1")

    results = ops.search_similar(vector=[0.25, 0.5, 0.75], limit=3, nprobe=17)

    assert results == []
    assert schema_mock_db.aql.execute.call_count == 1
    query = schema_mock_db.aql.execute.call_args[0][0]
    bind_vars = schema_mock_db.aql.execute.call_args[1]["bind_vars"]
    assert "vectors_track_cold__ast__lib1" in query
    assert "nProbe: 17" in query
    assert bind_vars == {"query_vector": [0.25, 0.5, 0.75], "limit": 3}


@pytest.mark.unit
def test_maintenance_drain_to_cold_executes_valid_aql() -> None:
    """Maintenance drain creates cold storage, migrates edges, and truncates hot vectors."""
    mock_db = MagicMock()
    hot_collection = MagicMock()
    cold_collection = MagicMock()
    hot_collection.count.return_value = 2
    mock_db.collection.side_effect = [hot_collection, cold_collection]
    mock_db.has_collection.side_effect = lambda name: name == "vectors_track_hot__ast__lib1"
    mock_db.aql.execute.side_effect = [iter([2]), iter([])]

    ops = VectorsTrackMaintenanceOperations(mock_db, backbone_id="ast", library_key="lib1")

    drained = ops.drain_to_cold()

    assert drained == 2
    assert mock_db.create_collection.call_count == 1
    assert mock_db.create_collection.call_args[0][0] == "vectors_track_cold__ast__lib1"
    assert mock_db.aql.execute.call_count == 2
    hot_collection.truncate.assert_called_once_with()


@pytest.mark.unit
def test_maintenance_backfill_genres_executes_valid_aql(schema_mock_db: Any) -> None:
    """Maintenance backfill executes valid AQL against the dynamic cold collection."""
    schema_mock_db.has_collection.return_value = True

    ops = VectorsTrackMaintenanceOperations(schema_mock_db, backbone_id="ast", library_key="lib1")

    updated = ops.backfill_genres()

    assert updated == 0
    assert schema_mock_db.aql.execute.call_count == 1
    bind_vars = schema_mock_db.aql.execute.call_args[1]["bind_vars"]
    assert bind_vars == {"@cold_coll": "vectors_track_cold__ast__lib1"}


@pytest.mark.unit
def test_schema_mock_db_rejects_unknown_collection() -> None:
    """Schema-aware mock rejects AQL that references a non-whitelisted collection."""
    mock_db = _make_schema_mock_db()

    with pytest.raises(AssertionError, match="Unknown collection 'not_a_real_collection'"):
        mock_db.aql.execute("FOR doc IN not_a_real_collection RETURN doc")


@pytest.mark.unit
def test_schema_mock_db_rejects_edge_insert_missing_from_to() -> None:
    """Schema-aware mock rejects edge INSERTs with no _from/_to fields at all."""
    mock_db = _make_schema_mock_db()

    with pytest.raises(AssertionError, match=r"missing '_from' field in document"):
        mock_db.aql.execute(
            "INSERT { value: @x } INTO file_has_state",
            bind_vars={"x": 1},
        )


@pytest.mark.unit
def test_schema_mock_db_preserves_collection_mock_behavior(schema_mock_db: Any) -> None:
    """Schema-aware mock still behaves like a normal MagicMock for collection handles."""
    collection = schema_mock_db.collection("vectors_track_hot__ast__lib1")

    assert isinstance(collection, MagicMock)


class TestDrainToCold:
    """Tests for VectorsTrackMaintenanceOperations.drain_to_cold."""

    @pytest.mark.unit
    def test_raises_value_error_when_hot_collection_missing(self) -> None:
        """Raises when the hot collection does not exist."""
        mock_db = MagicMock()
        mock_db.has_collection.return_value = False

        ops = VectorsTrackMaintenanceOperations(mock_db, backbone_id="ast", library_key="lib1")

        with pytest.raises(ValueError, match="Hot collection 'vectors_track_hot__ast__lib1' does not exist"):
            ops.drain_to_cold()

    @pytest.mark.unit
    def test_returns_zero_when_hot_collection_empty(self) -> None:
        """Short-circuits when the hot collection has no documents."""
        mock_db = MagicMock()
        hot_collection = MagicMock()
        cold_collection = MagicMock()
        hot_collection.count.return_value = 0
        mock_db.collection.side_effect = [hot_collection, cold_collection]
        mock_db.has_collection.return_value = True

        ops = VectorsTrackMaintenanceOperations(mock_db, backbone_id="ast", library_key="lib1")

        result = ops.drain_to_cold()

        assert result == 0
        mock_db.aql.execute.assert_not_called()

    @pytest.mark.unit
    def test_returns_drained_count(self) -> None:
        """Returns the drained count and truncates the hot collection after migration."""
        mock_db = MagicMock()
        hot_collection = MagicMock()
        cold_collection = MagicMock()
        hot_collection.count.return_value = 3
        mock_db.collection.side_effect = [hot_collection, cold_collection]
        mock_db.has_collection.return_value = True
        mock_db.aql.execute.side_effect = [iter([3]), iter([])]

        ops = VectorsTrackMaintenanceOperations(mock_db, backbone_id="ast", library_key="lib1")

        result = ops.drain_to_cold()

        assert result == 3
        hot_collection.truncate.assert_called_once_with()


class TestBackfillGenres:
    """Tests for VectorsTrackMaintenanceOperations.backfill_genres."""

    @pytest.mark.unit
    def test_raises_value_error_when_cold_collection_missing(self) -> None:
        """Raises when the cold collection does not exist."""
        mock_db = MagicMock()
        mock_db.has_collection.return_value = False

        ops = VectorsTrackMaintenanceOperations(mock_db, backbone_id="ast", library_key="lib1")

        with pytest.raises(ValueError, match="Cold collection 'vectors_track_cold__ast__lib1' does not exist"):
            ops.backfill_genres()

    @pytest.mark.unit
    def test_returns_updated_count(self) -> None:
        """Returns the number of cold documents updated."""
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_db.aql.execute.return_value = iter([7])

        ops = VectorsTrackMaintenanceOperations(mock_db, backbone_id="ast", library_key="lib1")

        result = ops.backfill_genres()

        assert result == 7

    @pytest.mark.unit
    def test_returns_zero_when_cursor_empty(self) -> None:
        """Returns zero when the backfill query yields no aggregate row."""
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_db.aql.execute.return_value = iter([])

        ops = VectorsTrackMaintenanceOperations(mock_db, backbone_id="ast", library_key="lib1")

        result = ops.backfill_genres()

        assert result == 0
