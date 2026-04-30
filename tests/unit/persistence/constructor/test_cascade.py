"""Tests for the CascadeEngine."""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest

from nomarr.persistence.constructor.cascade import CascadeEngine
from nomarr.persistence.schema import CollectionType


def _make_db_mock(
    edge_docs: list[dict[str, str]] | None = None,
    orphan_counts: list[int] | None = None,
) -> MagicMock:
    """Build a mock db where aql.execute returns controlled cursors."""
    db = MagicMock()
    call_count = [0]
    edge_documents = edge_docs or []
    remaining_edge_counts = orphan_counts or []

    def fake_execute(query: str, bind_vars: dict[str, Any] | None = None, **kwargs: object) -> object:
        del bind_vars
        normalized_query = query.strip()
        if "e._from IN @ids OR e._to IN @ids" in normalized_query:
            return iter(edge_documents)
        if "REMOVE key IN" in normalized_query:
            return iter([])
        if "LENGTH(FOR e IN" in normalized_query:
            if remaining_edge_counts:
                value = remaining_edge_counts[call_count[0] % len(remaining_edge_counts)]
                call_count[0] += 1
                return iter([value])
            return iter([0])
        if "REMOVE {_id: doc_id}" in normalized_query:
            return iter([])
        return iter([])

    db.aql.execute.side_effect = fake_execute
    return db


@pytest.mark.unit
@pytest.mark.mocked
class TestCascadeEngine:
    """Tests for CascadeEngine.cascade()."""

    SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "source_col": {
            "type": CollectionType.DOCUMENT,
            "capabilities": ["delete", "cascade"],
            "cascade": ["test_edge"],
            "edges": {
                "test_edge": {"target": "target_col", "direction": "OUTBOUND"},
            },
            "fields": {},
        },
        "test_edge": {
            "type": CollectionType.EDGE,
            "capabilities": [],
            "fields": {},
        },
        "target_col": {
            "type": CollectionType.DOCUMENT,
            "capabilities": ["delete"],
            "fields": {},
        },
    }

    def test_no_edges_returns_seed_count(self) -> None:
        """Cascade with no connected edges still deletes the seed document."""
        db = _make_db_mock(edge_docs=[])
        engine = CascadeEngine()

        result = engine.cascade(db, "source_col", ["source_col/1"], ["test_edge"], self.SCHEMA)

        assert result == 1

    def test_edge_removal_counted(self) -> None:
        """Cascade counts removed edge documents even when targets are not orphaned."""
        edges = [
            {"_key": "e1", "_from": "source_col/1", "_to": "target_col/1"},
            {"_key": "e2", "_from": "source_col/1", "_to": "target_col/2"},
        ]
        db = _make_db_mock(edge_docs=edges, orphan_counts=[1])
        engine = CascadeEngine()

        result = engine.cascade(db, "source_col", ["source_col/1"], ["test_edge"], self.SCHEMA)

        # 2 edges removed + 1 seed deleted
        assert result == 3

    def test_orphaned_target_document_is_counted(self) -> None:
        """Cascade removes now-orphaned target documents after edge cleanup."""
        edges = [{"_key": "e1", "_from": "source_col/1", "_to": "target_col/1"}]
        db = _make_db_mock(edge_docs=edges, orphan_counts=[0])
        engine = CascadeEngine()

        result = engine.cascade(db, "source_col", ["source_col/1"], ["test_edge"], self.SCHEMA)

        # 1 edge removed + 1 orphan target + 1 seed
        assert result == 3

    def test_deduplicates_ids_from_input_list(self) -> None:
        """Cascade deduplicates id lists before querying edge collections."""
        db = _make_db_mock(edge_docs=[])
        engine = CascadeEngine()

        result = engine.cascade(
            db,
            "source_col",
            ["source_col/1", "source_col/1"],
            ["test_edge"],
            self.SCHEMA,
        )

        # 1 deduplicated seed deleted
        assert result == 1
        first_call = db.aql.execute.call_args_list[0]
        assert first_call.kwargs["bind_vars"]["ids"] == ["source_col/1"]

    def test_target_with_remaining_edges_is_not_deleted(self) -> None:
        """A target connected to OTHER non-deleted documents must survive cascade.

        Regression guard: cascade must never delete shared/linked documents that
        still have at least one remaining edge after seed-edge cleanup.
        """
        edges = [{"_key": "e1", "_from": "source_col/1", "_to": "target_col/shared"}]
        # orphan_counts=[5] => target still has 5 remaining edges to other docs
        db = _make_db_mock(edge_docs=edges, orphan_counts=[5])
        engine = CascadeEngine()

        result = engine.cascade(db, "source_col", ["source_col/1"], ["test_edge"], self.SCHEMA)

        # 1 edge removed + 1 seed deleted; target_col/shared is NOT deleted
        assert result == 2

        remove_calls = [
            call
            for call in db.aql.execute.call_args_list
            if "REMOVE" in call.args[0] and "PARSE_IDENTIFIER" in call.args[0]
        ]
        # Only the seed collection should see a vertex REMOVE, never target_col
        for call in remove_calls:
            assert call.kwargs["bind_vars"]["@col"] == "source_col"

    def test_empty_ids_returns_zero(self) -> None:
        """Cascade with empty ids list returns 0 immediately."""
        db = MagicMock()
        engine = CascadeEngine()

        result = engine.cascade(db, "source_col", [], ["test_edge"], self.SCHEMA)

        assert result == 0
        db.aql.execute.assert_not_called()
