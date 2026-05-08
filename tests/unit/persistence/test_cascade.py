"""Unit tests for persistence cascade helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import nomarr.persistence.cascade as cascade
from nomarr.persistence.base_types import CASCADE, DETACH, INBOUND, OUTBOUND, EdgeDef


@pytest.mark.unit
@pytest.mark.mocked
class TestGatherConcreteNames:
    """Tests for ``gather_concrete_names``."""

    def test_extracts_names_from_instances(self) -> None:
        """Collection instance names are extracted into target and edge lists."""
        doc_one = MagicMock()
        doc_one._name = "doc_one"
        doc_two = MagicMock()
        doc_two._name = "doc_two"
        edge = MagicMock()
        edge._name = "rel_edges"

        target_names, edge_names = cascade.gather_concrete_names([doc_one, doc_two], [edge])

        assert target_names == ["doc_one", "doc_two"]
        assert edge_names == ["rel_edges"]

    def test_deduplicates_target_names(self) -> None:
        """Duplicate target collection names are returned once."""
        first = MagicMock()
        first._name = "dup_docs"
        second = MagicMock()
        second._name = "dup_docs"

        target_names, _ = cascade.gather_concrete_names([first, second], [])

        assert target_names == ["dup_docs"]

    def test_sorts_target_names(self) -> None:
        """Target collection names are sorted alphabetically."""
        z_col = MagicMock()
        z_col._name = "z_col"
        a_col = MagicMock()
        a_col._name = "a_col"

        target_names, _ = cascade.gather_concrete_names([z_col, a_col], [])

        assert target_names == ["a_col", "z_col"]

    def test_deduplicates_and_sorts_edge_names(self) -> None:
        """Edge collection names are deduplicated and sorted."""
        z_edge = MagicMock()
        z_edge._name = "z_edge"
        a_edge = MagicMock()
        a_edge._name = "a_edge"
        dup_edge = MagicMock()
        dup_edge._name = "a_edge"

        _, edge_names = cascade.gather_concrete_names([], [z_edge, a_edge, dup_edge])

        assert edge_names == ["a_edge", "z_edge"]

    def test_merges_extra_vector_names(self) -> None:
        """Extra vector names are merged into target collection names."""
        doc = MagicMock()
        doc._name = "docs"

        target_names, _ = cascade.gather_concrete_names(
            [doc],
            [],
            extra_vector_names=["vectors_hot", "vectors_cold"],
        )

        assert target_names == ["docs", "vectors_cold", "vectors_hot"]

    def test_no_extra_vector_names_returns_doc_names_only(self) -> None:
        """Without extra vector names, only document collection names are returned."""
        doc = MagicMock()
        doc._name = "docs"

        target_names, _ = cascade.gather_concrete_names([doc], [])

        assert target_names == ["docs"]

    def test_merged_result_is_sorted(self) -> None:
        """Merged document and vector names are sorted together."""
        doc = MagicMock()
        doc._name = "z_col"

        target_names, _ = cascade.gather_concrete_names([doc], [], extra_vector_names=["a_vec"])

        assert target_names == ["a_vec", "z_col"]


@pytest.mark.unit
class TestCascadeEdgeNames:
    """Tests for ``_cascade_edge_names``."""

    def test_includes_cascade_outbound_edges(self) -> None:
        """Only outbound cascade edges are included."""

        class CascadeEdge:
            _name = "cascade_edge"

        class DetachEdge:
            _name = "detach_edge"

        class InboundCascadeEdge:
            _name = "inbound_cascade_edge"

        class Target:
            EDGES = ()

        class Owner:
            EDGES = (
                EdgeDef(via=CascadeEdge, direction=OUTBOUND, target=Target, on_delete=CASCADE),
                EdgeDef(via=DetachEdge, direction=OUTBOUND, target=Target, on_delete=DETACH),
                EdgeDef(via=InboundCascadeEdge, direction=INBOUND, target=Target, on_delete=CASCADE),
            )

        assert cascade._cascade_edge_names(Owner) == ["cascade_edge"]

    def test_traverses_transitively(self) -> None:
        """Cascade edge discovery walks through reachable cascade targets."""

        class RootEdge:
            _name = "root_edge"

        class ChildEdge:
            _name = "child_edge"

        class Grandchild:
            EDGES = ()

        class Child:
            EDGES = (EdgeDef(via=ChildEdge, direction=OUTBOUND, target=Grandchild, on_delete=CASCADE),)

        class Root:
            EDGES = (EdgeDef(via=RootEdge, direction=OUTBOUND, target=Child, on_delete=CASCADE),)

        assert cascade._cascade_edge_names(Root) == ["root_edge", "child_edge"]

    def test_cycle_guard_prevents_infinite_recursion(self) -> None:
        """Cycles are visited once without recursing forever."""

        class EdgeAB:
            _name = "edge_ab"

        class EdgeBA:
            _name = "edge_ba"

        class NodeA:
            EDGES = ()

        class NodeB:
            EDGES = (EdgeDef(via=EdgeBA, direction=OUTBOUND, target=NodeA, on_delete=CASCADE),)

        NodeA.EDGES = (EdgeDef(via=EdgeAB, direction=OUTBOUND, target=NodeB, on_delete=CASCADE),)

        result = cascade._cascade_edge_names(NodeA)

        assert "edge_ab" in result
        assert "edge_ba" in result

    def test_returns_empty_for_no_edges(self) -> None:
        """Classes without edges produce an empty cascade edge list."""

        class Owner:
            EDGES = ()

        assert cascade._cascade_edge_names(Owner) == []


@pytest.mark.unit
class TestCompileCascadeAql:
    """Tests for ``_compile_cascade_aql``."""

    @staticmethod
    def _make_owner_class() -> type:
        class RelEdges:
            _name = "rel_edges"

        class TargetDocs:
            EDGES = ()

        class OwnerDocs:
            EDGES = (EdgeDef(via=RelEdges, direction=OUTBOUND, target=TargetDocs, on_delete=CASCADE),)

        return OwnerDocs

    def test_contains_starts_bind_var(self) -> None:
        """Compiled AQL iterates over the @starts bind variable."""
        owner_cls = self._make_owner_class()

        aql = cascade._compile_cascade_aql("owner_docs", owner_cls, ["owner_docs", "target_docs"], ["rel_edges"])

        assert "FOR start_id IN @starts" in aql

    def test_contains_cascade_edge_name(self) -> None:
        """Compiled AQL embeds the cascade edge collection name."""
        owner_cls = self._make_owner_class()

        aql = cascade._compile_cascade_aql("owner_docs", owner_cls, ["owner_docs", "target_docs"], ["rel_edges"])

        assert "rel_edges" in aql

    def test_contains_remove_for_owner_collection(self) -> None:
        """Compiled AQL removes the original owner documents at the end."""
        owner_cls = self._make_owner_class()

        aql = cascade._compile_cascade_aql("owner_docs", owner_cls, ["owner_docs", "target_docs"], ["rel_edges"])

        assert "REMOVE PARSE_IDENTIFIER(start_id).key IN owner_docs" in aql

    def test_ends_with_return_1(self) -> None:
        """Compiled AQL terminates with RETURN 1."""
        owner_cls = self._make_owner_class()

        aql = cascade._compile_cascade_aql("owner_docs", owner_cls, ["owner_docs", "target_docs"], ["rel_edges"])

        assert aql.endswith("RETURN 1")

    def test_excludes_owner_from_orphan_target_loop(self) -> None:
        """The owner collection is excluded from orphan target removal loops."""
        owner_cls = self._make_owner_class()

        aql = cascade._compile_cascade_aql("owner_docs", owner_cls, ["owner_docs", "target_docs"], ["rel_edges"])

        assert 'STARTS_WITH(orphan_id_0, "owner_docs/")' not in aql

    def test_includes_target_collection_in_orphan_loop(self) -> None:
        """Non-owner target collections are included in orphan removal loops."""
        owner_cls = self._make_owner_class()

        aql = cascade._compile_cascade_aql("owner_docs", owner_cls, ["owner_docs", "target_docs"], ["rel_edges"])

        assert 'STARTS_WITH(orphan_id_0, "target_docs/")' in aql

    def test_empty_target_names_after_exclusion(self) -> None:
        """No orphan target loops are emitted when only the owner collection remains."""
        owner_cls = self._make_owner_class()

        aql = cascade._compile_cascade_aql("owner_docs", owner_cls, ["owner_docs"], ["rel_edges"])

        assert "STARTS_WITH(orphan_id_" not in aql

    def test_no_cascade_edges_produces_simple_aql(self) -> None:
        """Without cascade edges, the compiler emits the simple single-step delete AQL."""

        class OwnerDocs:
            EDGES = ()

        aql = cascade._compile_cascade_aql("owner_docs", OwnerDocs, ["owner_docs"], [])

        assert "FOR start_id IN @starts" in aql
        assert "REMOVE PARSE_IDENTIFIER(start_id).key IN owner_docs" in aql
        assert aql.endswith("RETURN 1")
        assert "LET subgraph" not in aql
