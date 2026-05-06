"""Unit tests for persistence base descriptors and cascade helpers."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

import nomarr.persistence.base as base
from nomarr.persistence.arango_client import SafeDatabase


def _make_document_collection(
    class_name: str,
    collection_name: str,
    *,
    edges: list[base.EdgeDef] | None = None,
) -> type[base.DocumentCollection]:
    attrs: dict[str, Any] = {"_name": collection_name}
    if edges is not None:
        attrs["EDGES"] = edges
    return cast("type[base.DocumentCollection]", type(class_name, (base.DocumentCollection,), attrs))


def _make_vector_collection(class_name: str, collection_name: str) -> type[base.VectorCollection]:
    attrs = {
        "_name": collection_name,
        "VECTOR_TIER": "hot",
        "NAME_PATTERN": collection_name,
    }
    return cast("type[base.VectorCollection]", type(class_name, (base.VectorCollection,), attrs))


def _make_edge_collection(
    class_name: str,
    collection_name: str,
    from_collection: type[base.DocumentCollection],
    to_collection: type[base.DocumentCollection | base.VectorCollection],
) -> type[base.EdgeCollection]:
    attrs = {
        "_name": collection_name,
        "FROM_COLLECTION": from_collection,
        "TO_COLLECTION": to_collection,
    }
    return cast("type[base.EdgeCollection]", type(class_name, (base.EdgeCollection,), attrs))


@pytest.mark.unit
@pytest.mark.mocked
class TestBoundCollectionGet:
    """Tests for ``_BoundCollectionGet`` dispatch behavior."""

    def test_no_criteria_calls_get_many_by_filter_with_empty_dict(self) -> None:
        """No criteria dispatches to ``get_many_by_filter`` with an empty filter."""
        collection = _make_document_collection("GetDispatchCollection", "get_dispatch")
        safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        collection._db = safe_db

        with patch("nomarr.persistence.base.get_many_by_filter", return_value=[{"_key": "1"}]) as get_many_mock:
            result = base._BoundCollectionGet(collection)(limit=5, offset=2)

        assert result == [{"_key": "1"}]
        get_many_mock.assert_called_once_with(safe_db, "get_dispatch", {}, limit=5, offset=2)

    def test_single_known_field_delegates_to_bound_field_accessor_get(self) -> None:
        """A single known field uses the field accessor ``get`` path."""
        collection = _make_document_collection("KnownFieldCollection", "known_field_docs")
        accessor = base._BoundFieldAccessor(collection, "slug", unique=True)
        accessor_get = MagicMock(return_value={"_key": "doc-1"})
        accessor_get.many = MagicMock()
        accessor.get = accessor_get
        collection.slug = accessor

        result = base._BoundCollectionGet(collection)(slug="alpha")

        assert result == {"_key": "doc-1"}
        accessor_get.assert_called_once_with("alpha")
        accessor_get.many.assert_not_called()

    def test_single_known_field_with_limit_delegates_to_accessor_get_many(self) -> None:
        """Known-field lookups with paging use ``accessor.get.many``."""
        collection = _make_document_collection("KnownFieldPagedCollection", "known_field_paged_docs")
        accessor = base._BoundFieldAccessor(collection, "slug", unique=True)
        accessor_get = MagicMock()
        accessor_get.many = MagicMock(return_value=[{"_key": "doc-2"}])
        accessor.get = accessor_get
        collection.slug = accessor

        result = base._BoundCollectionGet(collection)(slug="alpha", limit=10, offset=3)

        assert result == [{"_key": "doc-2"}]
        accessor_get.assert_not_called()
        accessor_get.many.assert_called_once_with("alpha", limit=10, offset=3)

    def test_single_unknown_field_calls_get_many_by_field(self) -> None:
        """A single unknown field falls back to ``get_many_by_field``."""
        collection = _make_document_collection("UnknownFieldCollection", "unknown_field_docs")
        safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        collection._db = safe_db

        with patch(
            "nomarr.persistence.base.get_many_by_field", return_value=[{"_key": "doc-3"}]
        ) as get_many_by_field_mock:
            result = base._BoundCollectionGet(collection)(slug="beta", limit=4, offset=1)

        assert result == [{"_key": "doc-3"}]
        get_many_by_field_mock.assert_called_once_with(
            safe_db,
            "unknown_field_docs",
            "slug",
            "beta",
            limit=4,
            offset=1,
        )

    def test_multiple_fields_calls_get_many_by_filter(self) -> None:
        """Multiple criteria dispatch to ``get_many_by_filter``."""
        collection = _make_document_collection("MultiCriteriaCollection", "multi_criteria_docs")
        safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        collection._db = safe_db

        with patch("nomarr.persistence.base.get_many_by_filter", return_value=[{"_key": "doc-4"}]) as get_many_mock:
            result = base._BoundCollectionGet(collection)(slug="beta", status="ready", limit=7, offset=6)

        assert result == [{"_key": "doc-4"}]
        get_many_mock.assert_called_once_with(
            safe_db,
            "multi_criteria_docs",
            {"slug": "beta", "status": "ready"},
            limit=7,
            offset=6,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestBoundCollectionDelete:
    """Tests for ``_BoundCollectionDelete`` dispatch behavior."""

    def test_no_criteria_calls_truncate_and_returns_zero(self) -> None:
        """No criteria truncates the collection and returns ``0``."""
        collection = _make_document_collection("DeleteAllCollection", "delete_all_docs")
        safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        collection._db = safe_db

        with patch("nomarr.persistence.base.truncate") as truncate_mock:
            result = base._BoundCollectionDelete(collection)()

        assert result == 0
        truncate_mock.assert_called_once_with(safe_db, "delete_all_docs")

    def test_single_field_calls_delete_by_field(self) -> None:
        """A single criterion deletes by field."""
        collection = _make_document_collection("DeleteSingleFieldCollection", "delete_single_field_docs")
        safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        collection._db = safe_db

        with patch("nomarr.persistence.base.delete_by_field", return_value=3) as delete_by_field_mock:
            result = base._BoundCollectionDelete(collection)(slug="alpha")

        assert result == 3
        delete_by_field_mock.assert_called_once_with(safe_db, "delete_single_field_docs", "slug", "alpha")

    def test_multiple_fields_calls_delete_by_filter(self) -> None:
        """Multiple criteria delete via the filter path."""
        collection = _make_document_collection("DeleteMultiFieldCollection", "delete_multi_field_docs")
        safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        collection._db = safe_db

        with patch("nomarr.persistence.base.delete_by_filter", return_value=5) as delete_by_filter_mock:
            result = base._BoundCollectionDelete(collection)(slug="alpha", status="ready")

        assert result == 5
        delete_by_filter_mock.assert_called_once_with(
            safe_db,
            "delete_multi_field_docs",
            {"slug": "alpha", "status": "ready"},
        )

    def test_in_calls_delete_in_by_field(self) -> None:
        """``in_`` deletes by one field across many values."""
        collection = _make_document_collection("DeleteInCollection", "delete_in_docs")
        safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        collection._db = safe_db

        with patch("nomarr.persistence.base.delete_in_by_field", return_value=2) as delete_in_mock:
            result = base._BoundCollectionDelete(collection).in_(slug=["a", "b"])

        assert result == 2
        delete_in_mock.assert_called_once_with(safe_db, "delete_in_docs", "slug", ["a", "b"])

    def test_unreferenced_calls_delete_unreferenced(self) -> None:
        """``unreferenced`` forwards to the dedicated delete verb."""
        collection = _make_document_collection("DeleteUnreferencedCollection", "delete_unreferenced_docs")
        safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        collection._db = safe_db

        with patch("nomarr.persistence.base.delete_unreferenced", return_value=4) as delete_unreferenced_mock:
            result = base._BoundCollectionDelete(collection).unreferenced("doc_edges")

        assert result == 4
        delete_unreferenced_mock.assert_called_once_with(safe_db, "delete_unreferenced_docs", "doc_edges")

    def test_cascade_property_returns_none_when_no_cascade_compiled(self) -> None:
        """``cascade`` is ``None`` until a compiled cascade function is attached."""
        collection = _make_document_collection("DeleteCascadeNoneCollection", "delete_cascade_none_docs")

        assert base._BoundCollectionDelete(collection).cascade is None

    def test_cascade_property_returns_callable_when_cascade_compiled(self) -> None:
        """``cascade`` exposes the compiled cascade delete callable."""
        collection = _make_document_collection("DeleteCascadeCallableCollection", "delete_cascade_callable_docs")

        def cascade_delete(ids: list[str]) -> int:
            return len(ids)

        collection._cascade_delete_fn = cascade_delete

        assert base._BoundCollectionDelete(collection).cascade is cascade_delete


@pytest.mark.unit
@pytest.mark.mocked
class TestBoundTransition:
    """Tests for ``_BoundTransition``."""

    def test_calls_transition_verb_with_correct_edge_name(self) -> None:
        """Transitions use the snake-cased first edge class name."""
        source = _make_document_collection("TransitionSourceCollection", "transition_sources")
        target = _make_document_collection("TransitionTargetCollection", "transition_targets")
        edge = _make_edge_collection("TransitionLinkEdge", "transition_links", source, target)
        safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))

        state_graph = cast(
            "type[base.StateGraphCollection]",
            type(
                "TransitionGraph",
                (base.StateGraphCollection,),
                {
                    "_name": "transition_graph",
                    "_db": safe_db,
                    "EDGES": [base.EdgeDef(via=edge, direction=base.OUTBOUND, target=target, on_delete=base.CASCADE)],
                },
            ),
        )

        with patch("nomarr.persistence.base.transition_verb") as transition_mock:
            base._BoundTransition(state_graph)(["library_files/1"], "queued", "processed")

        transition_mock.assert_called_once_with(
            safe_db,
            "transition_link_edge",
            ["library_files/1"],
            "queued",
            "processed",
        )

    def test_raises_value_error_when_edges_is_empty(self) -> None:
        """Transitions require at least one edge definition."""
        state_graph = cast(
            "type[base.StateGraphCollection]",
            type(
                "EmptyTransitionGraph", (base.StateGraphCollection,), {"_name": "empty_transition_graph", "EDGES": []}
            ),
        )

        with pytest.raises(ValueError, match="has no EDGES defined"):
            base._BoundTransition(state_graph)(["library_files/1"], "queued", "processed")


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldDescriptor:
    """Tests for ``_FieldDescriptor``."""

    def test_get_from_class_returns_bound_field_accessor(self) -> None:
        """Class access returns a ``_BoundFieldAccessor`` instance."""

        class Owner:
            _db = MagicMock()
            _name = "owner_docs"
            slug = base._FieldDescriptor("slug", unique=True)

        accessor = Owner.slug

        assert isinstance(accessor, base._BoundFieldAccessor)
        assert accessor._cls is Owner
        assert accessor._field_name == "slug"
        assert accessor._unique is True

    def test_get_caches_accessor_on_owner_class(self) -> None:
        """Descriptor access caches the created accessor on the owner class."""

        class Owner:
            _db = MagicMock()
            _name = "owner_docs"
            slug = base._FieldDescriptor("slug", unique=False)

        first = Owner.slug
        second = Owner.slug

        assert first is second
        assert Owner.__dict__["_bound_field_slug"] is first

    def test_get_from_instance_uses_type_of_instance(self) -> None:
        """Instance access resolves the accessor against ``type(instance)``."""

        class Owner:
            _db = MagicMock()
            _name = "owner_docs"
            slug = base._FieldDescriptor("slug", unique=False)

        owner = Owner()

        assert owner.slug is Owner.slug

    def test_set_raises_attribute_error(self) -> None:
        """Field descriptors are read-only."""

        class Owner:
            _db = MagicMock()
            _name = "owner_docs"
            slug = base._FieldDescriptor("slug", unique=False)

        owner = Owner()

        with pytest.raises(AttributeError, match="read-only"):
            owner.slug = "updated"


@pytest.mark.unit
@pytest.mark.mocked
class TestCompileCascadeQuery:
    """Tests for ``_compile_cascade_query``."""

    def _build_query_fixture(
        self,
    ) -> tuple[type[base.DocumentCollection], list[base.EdgeDef], type[base.EdgeCollection]]:
        root = _make_document_collection("CascadeQueryRoot", "cascade_query_roots")
        child = _make_document_collection("CascadeQueryChild", "cascade_query_children")
        edge = _make_edge_collection("CascadeQueryEdge", "cascade_query_edges", root, child)
        root.EDGES = [base.EdgeDef(via=edge, direction=base.OUTBOUND, target=child, on_delete=base.CASCADE)]
        return root, root.EDGES, edge

    def test_output_contains_starts_bind_var(self) -> None:
        """Compiled cascade AQL iterates over ``@starts``."""
        root, cascade_defs, edge = self._build_query_fixture()

        def fake_iter(base_cls: type[Any]) -> Any:
            if base_cls is base.EdgeCollection:
                return iter([edge])
            if base_cls is base.DocumentCollection:
                return iter([root])
            if base_cls is base.VectorCollection:
                return iter([])
            return iter([])

        with patch("nomarr.persistence.base._iter_concrete_subclasses", side_effect=fake_iter):
            aql = base._compile_cascade_query(root, "cascade_query_roots", cascade_defs)

        assert "FOR start_id IN @starts" in aql

    def test_output_contains_remove_for_collection(self) -> None:
        """Compiled cascade AQL removes the starting collection documents."""
        root, cascade_defs, edge = self._build_query_fixture()

        def fake_iter(base_cls: type[Any]) -> Any:
            if base_cls is base.EdgeCollection:
                return iter([edge])
            if base_cls is base.DocumentCollection:
                return iter([root])
            if base_cls is base.VectorCollection:
                return iter([])
            return iter([])

        with patch("nomarr.persistence.base._iter_concrete_subclasses", side_effect=fake_iter):
            aql = base._compile_cascade_query(root, "cascade_query_roots", cascade_defs)

        assert "REMOVE PARSE_IDENTIFIER(start_id).key IN cascade_query_roots" in aql

    def test_output_contains_cascade_edge_name(self) -> None:
        """Compiled cascade AQL includes the cascade edge collection name."""
        root, cascade_defs, edge = self._build_query_fixture()

        def fake_iter(base_cls: type[Any]) -> Any:
            if base_cls is base.EdgeCollection:
                return iter([edge])
            if base_cls is base.DocumentCollection:
                return iter([root])
            if base_cls is base.VectorCollection:
                return iter([])
            return iter([])

        with patch("nomarr.persistence.base._iter_concrete_subclasses", side_effect=fake_iter):
            aql = base._compile_cascade_query(root, "cascade_query_roots", cascade_defs)

        assert "cascade_query_edges" in aql

    def test_output_ends_with_return_1(self) -> None:
        """Compiled cascade AQL ends with ``RETURN 1``."""
        root, cascade_defs, edge = self._build_query_fixture()

        def fake_iter(base_cls: type[Any]) -> Any:
            if base_cls is base.EdgeCollection:
                return iter([edge])
            if base_cls is base.DocumentCollection:
                return iter([root])
            if base_cls is base.VectorCollection:
                return iter([])
            return iter([])

        with patch("nomarr.persistence.base._iter_concrete_subclasses", side_effect=fake_iter):
            aql = base._compile_cascade_query(root, "cascade_query_roots", cascade_defs)

        assert aql.endswith("RETURN 1")


@pytest.mark.unit
@pytest.mark.mocked
class TestCompileAndAttachCascade:
    """Tests for ``_compile_and_attach_cascade``."""

    def _build_cascade_owner(self) -> type[base.DocumentCollection]:
        root = _make_document_collection("AttachCascadeRoot", "attach_cascade_roots")
        child = _make_document_collection("AttachCascadeChild", "attach_cascade_children")
        edge = _make_edge_collection("AttachCascadeEdge", "attach_cascade_edges", root, child)
        root.EDGES = [base.EdgeDef(via=edge, direction=base.OUTBOUND, target=child, on_delete=base.CASCADE)]
        root._db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        return root

    def test_attaches_cascade_delete_fn_and_cascade_aql_to_class(self) -> None:
        """Cascade compilation stores both the AQL and the delete callable."""
        root = self._build_cascade_owner()

        with patch("nomarr.persistence.base._compile_cascade_query", return_value="COMPILED AQL") as compile_mock:
            base._compile_and_attach_cascade(root)

        compile_mock.assert_called_once()
        assert root._cascade_aql == "COMPILED AQL"
        assert callable(root._cascade_delete_fn)

    def test_skips_class_with_no_cascade_edges(self) -> None:
        """Collections without outbound cascade edges are ignored."""
        root = _make_document_collection("NoCascadeRoot", "no_cascade_roots", edges=[])

        with patch("nomarr.persistence.base._compile_cascade_query") as compile_mock:
            base._compile_and_attach_cascade(root)

        compile_mock.assert_not_called()
        assert root._cascade_aql is None
        assert root._cascade_delete_fn is None

    def test_cascade_delete_fn_raises_for_empty_list(self) -> None:
        """The attached cascade delete callable rejects empty input."""
        root = self._build_cascade_owner()

        with patch("nomarr.persistence.base._compile_cascade_query", return_value="COMPILED AQL"):
            base._compile_and_attach_cascade(root)

        cascade_delete = cast("Any", root._cascade_delete_fn)
        with pytest.raises(ValueError, match="non-empty list"):
            cascade_delete([])

    def test_cascade_delete_fn_calls_execute_aql_with_ids(self) -> None:
        """The attached callable executes the compiled AQL with ``starts`` ids."""
        root = self._build_cascade_owner()
        ids = ["attach_cascade_roots/1", "attach_cascade_roots/2"]

        with (
            patch("nomarr.persistence.base._compile_cascade_query", return_value="COMPILED AQL"),
            patch("nomarr.persistence.base._execute_aql", return_value=[1, 1]) as execute_aql_mock,
        ):
            base._compile_and_attach_cascade(root)
            cascade_delete = cast("Any", root._cascade_delete_fn)
            cascade_delete(ids)

        execute_aql_mock.assert_called_once_with(root._db, "COMPILED AQL", bind_vars={"starts": ids})

    def test_cascade_delete_fn_returns_len_of_ids(self) -> None:
        """The attached callable reports how many root ids it was asked to delete."""
        root = self._build_cascade_owner()
        ids = ["attach_cascade_roots/1", "attach_cascade_roots/2", "attach_cascade_roots/3"]

        with (
            patch("nomarr.persistence.base._compile_cascade_query", return_value="COMPILED AQL"),
            patch("nomarr.persistence.base._execute_aql", return_value=[1, 1, 1]),
        ):
            base._compile_and_attach_cascade(root)
            cascade_delete = cast("Any", root._cascade_delete_fn)
            result = cascade_delete(ids)

        assert result == 3


@pytest.mark.unit
@pytest.mark.mocked
class TestReattachVectorCascades:
    """Tests for ``reattach_vector_cascades``."""

    def test_recompiles_cascade_for_collection_with_vector_edge_target(self) -> None:
        """Vector-target cascade collections are recompiled with registered names."""
        root = _make_document_collection("VectorCascadeRoot", "vector_cascade_roots")
        target = _make_vector_collection("VectorCascadeTarget", "vector_cascade_targets")
        edge = _make_edge_collection("VectorCascadeEdge", "vector_cascade_edges", root, target)
        root.EDGES = [base.EdgeDef(via=edge, direction=base.OUTBOUND, target=target, on_delete=base.CASCADE)]
        registered_names = ["vectors_track_hot__model__library"]

        with (
            patch("nomarr.persistence.base._iter_concrete_subclasses", return_value=iter([root])),
            patch("nomarr.persistence.base._compile_and_attach_cascade") as compile_mock,
        ):
            base.reattach_vector_cascades(registered_names)

        compile_mock.assert_called_once_with(root, extra_vector_names=registered_names)

    def test_skips_collection_without_cascade_edges(self) -> None:
        """Collections without cascade edges are ignored."""
        root = _make_document_collection("NoCascadeReattachRoot", "no_cascade_reattach_roots", edges=[])

        with (
            patch("nomarr.persistence.base._iter_concrete_subclasses", return_value=iter([root])),
            patch("nomarr.persistence.base._compile_and_attach_cascade") as compile_mock,
        ):
            base.reattach_vector_cascades(["vectors_track_hot__model__library"])

        compile_mock.assert_not_called()

    def test_skips_collection_with_only_non_vector_targets(self) -> None:
        """Non-vector cascade targets do not trigger vector cascade recompilation."""
        root = _make_document_collection("NonVectorCascadeRoot", "non_vector_cascade_roots")
        target = _make_document_collection("NonVectorCascadeTarget", "non_vector_cascade_targets")
        edge = _make_edge_collection("NonVectorCascadeEdge", "non_vector_cascade_edges", root, target)
        root.EDGES = [base.EdgeDef(via=edge, direction=base.OUTBOUND, target=target, on_delete=base.CASCADE)]

        with (
            patch("nomarr.persistence.base._iter_concrete_subclasses", return_value=iter([root])),
            patch("nomarr.persistence.base._compile_and_attach_cascade") as compile_mock,
        ):
            base.reattach_vector_cascades(["vectors_track_hot__model__library"])

        compile_mock.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
class TestBindAllCollections:
    """Additional tests for ``bind_all_collections``."""

    def test_also_compiles_cascade_for_document_collections_with_cascade_edges(self) -> None:
        """Binding all collections also compiles cascade handlers for eligible documents."""
        safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        root = _make_document_collection("BindCascadeRoot", "bind_cascade_roots")
        target = _make_document_collection("BindCascadeTarget", "bind_cascade_targets")
        edge = _make_edge_collection("BindCascadeEdge", "bind_cascade_edges", root, target)
        root.EDGES = [base.EdgeDef(via=edge, direction=base.OUTBOUND, target=target, on_delete=base.CASCADE)]
        no_cascade = _make_document_collection("BindNoCascadeRoot", "bind_no_cascade_roots", edges=[])

        original_document_db = base.DocumentCollection._db
        original_edge_db = base.EdgeCollection._db
        original_vector_db = base.VectorCollection._db

        try:
            with (
                patch("nomarr.persistence.base._iter_concrete_subclasses", return_value=iter([root, no_cascade])),
                patch("nomarr.persistence.base._compile_and_attach_cascade") as compile_mock,
            ):
                base.bind_all_collections(safe_db)

            compile_mock.assert_called_once_with(root)
        finally:
            base.DocumentCollection._db = original_document_db
            base.EdgeCollection._db = original_edge_db
            base.VectorCollection._db = original_vector_db
