"""Tests for schema validation in SchemaConstructor."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from nomarr.persistence.constructor.builder import SchemaConstructor
from nomarr.persistence.schema import CollectionType, SchemaValidationError


def _make_constructor(mock_db: MagicMock) -> SchemaConstructor:
    """Build a SchemaConstructor instance without running __init__."""
    constructor = SchemaConstructor.__new__(SchemaConstructor)
    constructor._db = mock_db
    return constructor


def _make_minimal_schema(**overrides: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a minimal valid schema for testing."""
    base: dict[str, dict[str, Any]] = {
        "test_docs": {
            "type": CollectionType.DOCUMENT,
            "capabilities": ["insert", "delete"],
            "fields": {},
        },
        "test_edges": {
            "type": CollectionType.EDGE,
            "capabilities": [],
            "fields": {},
        },
        "test_state_graph": {
            "type": CollectionType.STATE_GRAPH,
            "capabilities": ["transition"],
            "edge_collection": "test_edges",
            "axes": {"active": ("test_state_graph/active", "test_state_graph/inactive")},
            "fields": {},
        },
        "test_template": {
            "type": CollectionType.TEMPLATE,
            "capabilities": ["ann_search"],
            "name_pattern": "test_template_{tier}__{lib}",
            "fields": {},
        },
    }
    base.update(overrides)
    return base


@pytest.mark.unit
@pytest.mark.mocked
class TestSchemaValidation:
    """Tests for SchemaConstructor.validate_schema()."""

    def setup_method(self) -> None:
        self.mock_db = MagicMock()

    def test_valid_schema_passes(self) -> None:
        """A schema with valid configuration raises no errors."""
        constructor = _make_constructor(self.mock_db)
        schema = _make_minimal_schema()

        constructor.validate_schema(schema)

    def test_ann_search_on_document_raises(self) -> None:
        """ann_search on a DOCUMENT collection raises SchemaValidationError."""
        constructor = _make_constructor(self.mock_db)
        schema = _make_minimal_schema(
            bad_col={
                "type": CollectionType.DOCUMENT,
                "capabilities": ["ann_search"],
                "fields": {},
            }
        )

        with pytest.raises(SchemaValidationError, match="ann_search"):
            constructor.validate_schema(schema)

    def test_ann_search_on_state_graph_raises(self) -> None:
        """ann_search on a STATE_GRAPH collection raises SchemaValidationError."""
        constructor = _make_constructor(self.mock_db)
        schema = _make_minimal_schema(
            bad_sg={
                "type": CollectionType.STATE_GRAPH,
                "capabilities": ["ann_search"],
                "edge_collection": "test_edges",
                "axes": {},
                "fields": {},
            }
        )

        with pytest.raises(SchemaValidationError, match="ann_search"):
            constructor.validate_schema(schema)

    def test_transition_on_document_raises(self) -> None:
        """transition on a DOCUMENT collection raises SchemaValidationError."""
        constructor = _make_constructor(self.mock_db)
        schema = _make_minimal_schema(
            bad_doc={
                "type": CollectionType.DOCUMENT,
                "capabilities": ["transition"],
                "fields": {},
            }
        )

        with pytest.raises(SchemaValidationError, match="transition"):
            constructor.validate_schema(schema)

    def test_cascade_target_not_in_schema_raises(self) -> None:
        """Cascade target not declared in schema raises SchemaValidationError."""
        constructor = _make_constructor(self.mock_db)
        schema = _make_minimal_schema(
            bad_cascade={
                "type": CollectionType.DOCUMENT,
                "capabilities": ["cascade"],
                "cascade": ["nonexistent_edge"],
                "fields": {},
            }
        )

        with pytest.raises(SchemaValidationError, match="nonexistent_edge"):
            constructor.validate_schema(schema)

    def test_cascade_target_not_edge_type_raises(self) -> None:
        """Cascade target that is not EDGE type raises SchemaValidationError."""
        constructor = _make_constructor(self.mock_db)
        schema = _make_minimal_schema(
            bad_cascade2={
                "type": CollectionType.DOCUMENT,
                "capabilities": ["cascade"],
                "cascade": ["test_docs"],
                "fields": {},
            }
        )

        with pytest.raises(SchemaValidationError, match="EDGE"):
            constructor.validate_schema(schema)

    def test_actual_schema_passes_validation(self) -> None:
        """The production SCHEMA in schema.py must pass validate_schema without error."""
        from nomarr.persistence.schema import SCHEMA

        constructor = _make_constructor(self.mock_db)

        constructor.validate_schema(SCHEMA)  # Must not raise

    def test_song_has_tags_to_field_has_aggregate_capability(self) -> None:
        """song_has_tags._to must declare aggregate capability (TASK-perf-batch-queries-A)."""
        from nomarr.persistence.schema import SCHEMA

        to_capabilities = SCHEMA["song_has_tags"]["fields"]["_to"]["capabilities"]
        assert "aggregate" in to_capabilities
