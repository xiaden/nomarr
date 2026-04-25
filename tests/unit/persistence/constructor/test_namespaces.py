"""Tests for namespace objects built by SchemaConstructor."""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.filter_types import Op
from nomarr.persistence.constructor.namespaces import (
    CollectionNamespace,
    FieldNamespace,
    GetModifierNamespace,
    IdGetManyNamespace,
    IdGetNamespace,
)
from nomarr.persistence.schema import CollectionType


def _build_ns(
    db: MagicMock,
    col_name: str,
    spec: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> Any:
    """Build a namespace without full SchemaConstructor validation."""
    return CollectionNamespace(
        db=db,
        collection_name=col_name,
        spec=spec,
        schema={} if schema is None else schema,
    )


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionNamespace:
    """Tests for CollectionNamespace construction from spec."""

    def test_has_insert_when_declared(self) -> None:
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": ["insert"], "fields": {}}

        namespace = _build_ns(db, "test_col", spec)

        assert callable(namespace.insert)

    def test_has_delete_when_declared(self) -> None:
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": ["delete"], "fields": {}}

        namespace = _build_ns(db, "test_col", spec)

        assert callable(namespace.delete)

    def test_has_count_when_declared(self) -> None:
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": ["count"], "fields": {}}

        namespace = _build_ns(db, "test_col", spec)

        assert callable(namespace.count)

    def test_field_namespace_attached_for_each_field(self) -> None:
        db = MagicMock()
        spec = {
            "type": CollectionType.DOCUMENT,
            "capabilities": [],
            "fields": {
                "name": {"type": "str", "capabilities": ["get"]},
                "status": {"type": "str", "capabilities": ["get", "update"]},
            },
        }

        namespace = _build_ns(db, "test_col", spec)

        assert isinstance(namespace.name, FieldNamespace)
        assert isinstance(namespace.status, FieldNamespace)

    def test_always_has_get_shorthand(self) -> None:
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": [], "fields": {}}

        namespace = _build_ns(db, "test_col", spec)

        assert hasattr(namespace, "get")
        assert callable(namespace.get)


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldNamespace:
    """Tests for FieldNamespace construction from field spec."""

    def test_get_attached_when_in_capabilities(self) -> None:
        db = MagicMock()
        spec = {
            "type": CollectionType.DOCUMENT,
            "capabilities": [],
            "fields": {"my_field": {"type": "str", "capabilities": ["get"]}},
        }

        namespace = _build_ns(db, "col", spec)

        assert isinstance(namespace.my_field.get, GetModifierNamespace)

    def test_update_attached_when_in_capabilities(self) -> None:
        db = MagicMock()
        spec = {
            "type": CollectionType.DOCUMENT,
            "capabilities": [],
            "fields": {"status": {"type": "str", "capabilities": ["get", "update"]}},
        }

        namespace = _build_ns(db, "col", spec)

        assert callable(namespace.status.update)

    def test_collect_attached_when_in_capabilities(self) -> None:
        db = MagicMock()
        spec = {
            "type": CollectionType.DOCUMENT,
            "capabilities": [],
            "fields": {"rel": {"type": "str", "capabilities": ["get", "collect"]}},
        }

        namespace = _build_ns(db, "col", spec)

        assert callable(namespace.rel.collect)


@pytest.mark.unit
@pytest.mark.mocked
class TestGetModifierNamespace:
    """Tests for GetModifierNamespace behavior."""

    def _build_get_modifier(self, unique: bool, db: MagicMock | None = None) -> GetModifierNamespace:
        database = MagicMock() if db is None else db
        return GetModifierNamespace(
            db=database,
            collection_name="test_col",
            field_name="test_field",
            field_spec={"unique": unique},
        )

    def test_call_dispatches_to_one_for_unique_field(self) -> None:
        modifier = self._build_get_modifier(unique=True)

        with patch.object(modifier, "_one", return_value={"_id": "test_col/1"}) as mock_one:
            modifier("some_value")

        mock_one.assert_called_once_with("some_value")

    def test_call_dispatches_to_many_for_non_unique_field(self) -> None:
        modifier = self._build_get_modifier(unique=False)

        with patch.object(modifier, "many", return_value=[]) as mock_many:
            modifier("some_value")

        mock_many.assert_called_once_with("some_value")

    def test_getattr_in_returns_in_alias(self) -> None:
        modifier = self._build_get_modifier(unique=False)

        alias = getattr(modifier, "in")

        assert callable(alias)
        assert alias.__self__ is modifier
        assert alias == modifier.in_

    def test_in_with_list_calls_get_in_verb(self) -> None:
        db = MagicMock()
        db.aql.execute.return_value = iter([{"_id": "col/1"}])
        modifier = self._build_get_modifier(unique=False, db=db)

        result = modifier.in_(["val1", "val2"])

        assert result == [{"_id": "col/1"}]

    def test_in_with_filter_dict_calls_comparison_verb(self) -> None:
        db = MagicMock()
        db.aql.execute.return_value = iter([])
        modifier = self._build_get_modifier(unique=False, db=db)

        result = modifier.in_({Op.LT: 100})

        assert result == []

    def test_one_not_available_on_non_unique_field(self) -> None:
        """Accessing .one on a non-unique field should raise AttributeError."""
        modifier = self._build_get_modifier(unique=False)

        with pytest.raises(AttributeError):
            _ = modifier.one


@pytest.mark.unit
@pytest.mark.mocked
class TestGetModifierNamespaceLike:
    """Tests for GetModifierNamespace.like()."""

    def test_like_calls_get_like_verb_and_returns_results(self) -> None:
        """like() delegates to get_like_by_field and returns its documents."""
        db = MagicMock()
        db.aql.execute.return_value = iter([{"_id": "col/1", "name": "rock n roll"}])
        modifier = GetModifierNamespace(
            db=db,
            collection_name="test_col",
            field_name="name",
            field_spec={"unique": False},
        )

        result = modifier.like("%rock%")

        assert result == [{"_id": "col/1", "name": "rock n roll"}]
        db.aql.execute.assert_called_once()
        aql = db.aql.execute.call_args[0][0]
        assert "LIKE" in aql

    def test_like_passes_limit_and_offset(self) -> None:
        """like() forwards limit and offset to the underlying verb."""
        db = MagicMock()
        db.aql.execute.return_value = iter([])
        modifier = GetModifierNamespace(
            db=db,
            collection_name="test_col",
            field_name="name",
            field_spec={"unique": False},
        )

        modifier.like("%test%", limit=5, offset=2)

        bind_vars = db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["pagination_offset"] == 2
        assert bind_vars["pagination_limit"] == 5

    def test_like_not_available_when_operators_excludes_it(self) -> None:
        """like() must not exist when operators.get does not include 'like'."""
        modifier = GetModifierNamespace(
            db=MagicMock(),
            collection_name="test_col",
            field_name="name",
            field_spec={"unique": False},
            collection_operators={"get": ["in"]},
        )

        assert not hasattr(modifier, "like")

    def test_like_available_when_operators_includes_it(self) -> None:
        """like() must exist when operators.get explicitly includes 'like'."""
        modifier = GetModifierNamespace(
            db=MagicMock(),
            collection_name="test_col",
            field_name="name",
            field_spec={"unique": False},
            collection_operators={"get": ["in", "like"]},
        )

        assert hasattr(modifier, "like")
        assert callable(modifier.like)

    def test_like_available_when_no_operators_config(self) -> None:
        """like() must exist when no collection_operators is given (backward-compatible default)."""
        modifier = GetModifierNamespace(
            db=MagicMock(),
            collection_name="test_col",
            field_name="name",
            field_spec={"unique": False},
        )

        assert hasattr(modifier, "like")
        assert callable(modifier.like)


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionNamespaceTransition:
    """Tests for CollectionNamespace._transition."""

    SPEC_WITH_EDGE: ClassVar[dict[str, Any]] = {
        "type": CollectionType.STATE_GRAPH,
        "capabilities": ["transition"],
        "edge_collection": "state_edges",
        "axes": {"active": ("sg/active", "sg/inactive")},
        "fields": {},
    }

    def test_transition_inserts_new_edge_when_no_old_edge(self) -> None:
        """With no existing edge, only the INSERT call is made."""
        db = MagicMock()
        # First call (SELECT for old edge) returns nothing; INSERT call returns iter([])
        db.aql.execute.side_effect = [iter([]), iter([])]

        ns = _build_ns(db, "sg", self.SPEC_WITH_EDGE)
        ns.transition(["sg/1"], "sg/inactive", "sg/active")

        assert db.aql.execute.call_count == 2
        insert_call_aql = db.aql.execute.call_args_list[1][0][0]
        assert "INSERT" in insert_call_aql

    def test_transition_removes_old_edge_then_inserts_new(self) -> None:
        """With an existing edge key, REMOVE is called before INSERT."""
        db = MagicMock()
        # SELECT returns old key; REMOVE then INSERT
        db.aql.execute.side_effect = [iter(["old_key"]), iter([]), iter([])]

        ns = _build_ns(db, "sg", self.SPEC_WITH_EDGE)
        ns.transition(["sg/1"], "sg/inactive", "sg/active")

        assert db.aql.execute.call_count == 3
        remove_call_aql = db.aql.execute.call_args_list[1][0][0]
        assert "REMOVE" in remove_call_aql

    def test_transition_raises_when_no_edge_collection(self) -> None:
        """Calling transition on a spec without edge_collection raises SchemaValidationError."""
        from nomarr.persistence.schema import SchemaValidationError

        db = MagicMock()
        spec_without_edge = {
            "type": CollectionType.STATE_GRAPH,
            "capabilities": ["transition"],
            "axes": {},
            "fields": {},
        }
        ns = _build_ns(db, "sg", spec_without_edge)

        with pytest.raises(SchemaValidationError):
            ns.transition(["sg/1"], "sg/inactive", "sg/active")

    def test_transition_accepts_single_item_id_list(self) -> None:
        """A single-item id list is processed without scalar normalization."""
        db = MagicMock()
        db.aql.execute.side_effect = [iter([]), iter([])]

        ns = _build_ns(db, "sg", self.SPEC_WITH_EDGE)
        ns.transition(["sg/1"], "sg/inactive", "sg/active")

        # Should not raise; 2 calls = SELECT + INSERT
        assert db.aql.execute.call_count == 2


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionNamespaceTraversal:
    """Tests for CollectionNamespace._traversal dispatch."""

    SPEC_WITH_TRAVERSAL: ClassVar[dict[str, Any]] = {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["traversal"],
        "edges": {
            "tracks_edge": {"target": "tracks", "direction": "OUTBOUND"},
        },
        "fields": {},
    }

    def test_traversal_dispatches_by_id_when_start_is_string(self) -> None:
        """When start is a str, dispatches to traversal_by_id."""
        db = MagicMock()
        db.aql.execute.return_value = iter([{"_id": "tracks/1"}])

        ns = _build_ns(db, "albums", self.SPEC_WITH_TRAVERSAL)
        result = ns.traversal("albums/1", "tracks_edge")

        assert result == [{"_id": "tracks/1"}]
        aql = db.aql.execute.call_args[0][0]
        assert "OUTBOUND" in aql
        assert "start_id" in db.aql.execute.call_args[1]["bind_vars"]

    def test_traversal_dispatches_by_filter_when_start_is_dict(self) -> None:
        """When start is a dict and no target_filter, uses traversal_by_filter."""
        db = MagicMock()
        db.aql.execute.return_value = iter([])

        ns = _build_ns(db, "albums", self.SPEC_WITH_TRAVERSAL)
        ns.traversal({"lib_id": "lib/1"}, "tracks_edge")

        bind_vars = db.aql.execute.call_args[1]["bind_vars"]
        assert "@col" in bind_vars
        assert "start_id" not in bind_vars

    def test_traversal_dispatches_to_target_filter_when_provided(self) -> None:
        """When start is a dict and target_filter is given, uses traversal_by_filter_with_target_filter."""
        db = MagicMock()
        db.aql.execute.return_value = iter([])

        ns = _build_ns(db, "albums", self.SPEC_WITH_TRAVERSAL)
        ns.traversal({"lib_id": "lib/1"}, "tracks_edge", target_filter={"genre": "rock"})

        aql = db.aql.execute.call_args[0][0]
        bind_vars = db.aql.execute.call_args[1]["bind_vars"]
        # target filter bind var should be present
        assert "tgt_val_0" in bind_vars
        assert aql.count("FILTER") >= 2

    def test_traversal_raises_attribute_error_for_undeclared_edge(self) -> None:
        """Traversal on an undeclared edge name raises AttributeError."""
        db = MagicMock()
        ns = _build_ns(db, "albums", self.SPEC_WITH_TRAVERSAL)

        with pytest.raises(AttributeError, match="undeclared_edge"):
            ns.traversal("albums/1", "undeclared_edge")


@pytest.mark.unit
@pytest.mark.mocked
class TestIdGetNamespace:
    """Tests for IdGetNamespace.id() delegation to get_one_by_id verb."""

    def _build_id_get(self, db: MagicMock) -> IdGetNamespace:
        return IdGetNamespace(db=db, collection_name="test_col")

    def test_id_delegates_to_verb_and_returns_document(self) -> None:
        """id() calls db.collection(name).get(doc_id) and returns the document."""
        db = MagicMock()
        db.collection.return_value.get.return_value = {"_id": "test_col/1", "name": "foo"}

        ns = self._build_id_get(db)
        result = ns.id("test_col/1")

        db.collection.assert_called_once_with("test_col")
        db.collection.return_value.get.assert_called_once_with("test_col/1")
        assert result == {"_id": "test_col/1", "name": "foo"}

    def test_id_returns_none_when_document_not_found(self) -> None:
        """id() propagates None when the document does not exist."""
        db = MagicMock()
        db.collection.return_value.get.return_value = None

        ns = self._build_id_get(db)
        result = ns.id("test_col/missing")

        assert result is None

    def test_call_shorthand_delegates_to_id(self) -> None:
        """__call__ is equivalent to .id() — same underlying verb invocation."""
        db = MagicMock()
        db.collection.return_value.get.return_value = {"_id": "test_col/2"}

        ns = self._build_id_get(db)
        result = ns("test_col/2")

        db.collection.return_value.get.assert_called_once_with("test_col/2")
        assert result == {"_id": "test_col/2"}


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionNamespaceMutationDispatch:
    """Tests that collection and field wrappers forward list-only mutation args."""

    _SPEC: ClassVar[dict[str, Any]] = {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert"],
        "fields": {},
    }

    def test_insert_single_item_list_calls_insert_many_and_returns_id_list(self) -> None:
        """Passing a single-item list to verbs.insert returns a list of inserted ``_id`` values."""
        db = MagicMock()
        db.collection.return_value.insert_many.return_value = [{"new": {"_id": "items/1"}}]

        ns = _build_ns(db, "items", self._SPEC)
        result = ns.insert([{"title": "foo"}])

        db.collection.assert_called_with("items")
        db.collection.return_value.insert_many.assert_called_once_with(
            [{"title": "foo"}],
            return_new=True,
            raise_on_document_error=True,
        )
        assert result == ["items/1"]

    def test_insert_list_calls_insert_many_and_returns_id_list(self) -> None:
        """Passing a list to verbs.insert returns a list of _id strings."""
        db = MagicMock()
        db.collection.return_value.insert_many.return_value = [
            {"new": {"_id": "items/1"}},
            {"new": {"_id": "items/2"}},
        ]

        ns = _build_ns(db, "items", self._SPEC)
        result = ns.insert([{"title": "foo"}, {"title": "bar"}])

        db.collection.assert_called_with("items")
        db.collection.return_value.insert_many.assert_called_once_with(
            [{"title": "foo"}, {"title": "bar"}],
            return_new=True,
            raise_on_document_error=True,
        )
        assert result == ["items/1", "items/2"]

    def test_field_upsert_forwards_docs_list_and_compound_match_field(self) -> None:
        """FieldNamespace.upsert forwards docs list and compound-key match fields unchanged."""
        db = MagicMock()
        spec = {
            "type": CollectionType.DOCUMENT,
            "capabilities": [],
            "fields": {"rel": {"type": "str", "capabilities": ["upsert"]}},
        }
        namespace = _build_ns(db, "tags", spec)

        with patch(
            "nomarr.persistence.constructor.namespaces.verbs.upsert_by_field",
            return_value=["tags/1"],
        ) as mock_upsert:
            result = namespace.rel.upsert(
                [{"rel": "genre", "value": "rock"}],
                match_field=["rel", "value"],
            )

        assert result == ["tags/1"]
        mock_upsert.assert_called_once_with(
            db,
            "tags",
            ["rel", "value"],
            [{"rel": "genre", "value": "rock"}],
        )

    def test_delete_forwards_ids_list_to_delete_verb(self) -> None:
        """CollectionNamespace.delete() forwards the ids list unchanged to verbs.delete_by_ids."""
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": ["delete"], "fields": {}}
        namespace = _build_ns(db, "items", spec)

        with patch("nomarr.persistence.constructor.namespaces.verbs.delete_by_ids") as mock_delete:
            namespace.delete(["items/1", "items/2"])

        mock_delete.assert_called_once_with(db, "items", ["items/1", "items/2"])


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionNamespaceCascadeDispatch:
    """Tests for CollectionNamespace.cascade() dispatch behavior."""

    def test_cascade_returns_zero_when_no_cascade_targets_in_spec(self) -> None:
        """cascade() returns 0 and does not call the engine when no targets are declared."""
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": ["cascade"], "fields": {}}
        namespace = _build_ns(db, "source_col", spec)

        with patch("nomarr.persistence.constructor.cascade.CascadeEngine.cascade") as mock_cascade:
            result = namespace.cascade(["col/1"])

        assert result == 0
        mock_cascade.assert_not_called()

    def test_cascade_forwards_ids_list_to_engine(self) -> None:
        """cascade() forwards the ids list and schema context to CascadeEngine.cascade()."""
        db = MagicMock()
        spec = {
            "type": CollectionType.DOCUMENT,
            "capabilities": ["cascade"],
            "cascade": ["some_edge"],
            "fields": {},
        }
        schema = {
            "source_col": spec,
            "some_edge": {
                "type": CollectionType.EDGE,
                "capabilities": [],
                "fields": {},
            },
        }
        namespace = _build_ns(db, "source_col", spec, schema=schema)

        with patch(
            "nomarr.persistence.constructor.cascade.CascadeEngine.cascade",
            return_value=2,
        ) as mock_cascade:
            result = namespace.cascade(["col/1", "col/2"])

        assert result == 2
        mock_cascade.assert_called_once()
        args = mock_cascade.call_args.args
        assert args[0] is db
        assert args[1] == "source_col"
        assert args[2] == ["col/1", "col/2"]
        assert args[3] == ["some_edge"]
        assert args[4] == schema
        assert args[5] is None


@pytest.mark.unit
@pytest.mark.mocked
class TestIdGetManyNamespace:
    """Tests for IdGetManyNamespace.by_filter delegation."""

    def _build_id_get_many(self, db: MagicMock) -> IdGetManyNamespace:
        return IdGetManyNamespace(db=db, collection_name="tags")

    def test_by_filter_forwards_filter_dict_and_pagination(self) -> None:
        """by_filter() forwards the filter dict and pagination bind vars to the verb."""
        db = MagicMock()
        db.aql.execute.return_value = iter([{"_id": "tags/1"}])

        ns = self._build_id_get_many(db)
        result = ns.by_filter(
            {"rel": "genre", "value": "rock"},
            limit=10,
            offset=5,
        )

        assert result == [{"_id": "tags/1"}]
        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        bind_vars = call_args.kwargs["bind_vars"]
        assert "FILTER doc[@f0] == @v0 AND doc[@f1] == @v1" in aql
        assert "LIMIT @pagination_offset, @pagination_limit" in aql
        assert bind_vars == {
            "@col": "tags",
            "f0": "rel",
            "v0": "genre",
            "f1": "value",
            "v1": "rock",
            "pagination_offset": 5,
            "pagination_limit": 10,
        }

    def test_by_filter_is_accessible_from_collection_get_many_namespace(self) -> None:
        """CollectionNamespace.get.many exposes by_filter() for multi-field lookups."""
        db = MagicMock()
        db.aql.execute.return_value = iter([])
        spec = {"type": CollectionType.DOCUMENT, "capabilities": [], "fields": {}}

        namespace = _build_ns(db, "tags", spec)

        assert callable(namespace.get.many.by_filter)
        assert isinstance(namespace.get.many, IdGetManyNamespace)
        assert namespace.get.many.by_filter({"rel": "genre"}) == []


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionNamespaceFilterCapabilities:
    """Tests for CollectionNamespace filter helper attachment and delegation."""

    def test_count_by_filter_attached_when_count_declared(self) -> None:
        """count_by_filter() is attached when collection capabilities include count."""
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": ["count"], "fields": {}}

        namespace = _build_ns(db, "tags", spec)

        assert callable(namespace.count_by_filter)

    def test_count_by_filter_calls_underlying_verb_and_returns_count(self) -> None:
        """count_by_filter() delegates to verbs.count_by_filter and returns its count."""
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": ["count"], "fields": {}}
        namespace = _build_ns(db, "tags", spec)

        with patch(
            "nomarr.persistence.constructor.namespaces.verbs.count_by_filter",
            return_value=3,
        ) as mock_count:
            result = namespace.count_by_filter({"rel": "genre"})

        assert result == 3
        mock_count.assert_called_once_with(db, "tags", {"rel": "genre"})

    def test_delete_by_filter_attached_when_delete_declared(self) -> None:
        """delete_by_filter() is attached when collection capabilities include delete."""
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": ["delete"], "fields": {}}

        namespace = _build_ns(db, "tags", spec)

        assert callable(namespace.delete_by_filter)

    def test_delete_by_filter_calls_underlying_verb_and_returns_count(self) -> None:
        """delete_by_filter() delegates to verbs.delete_by_filter and returns its count."""
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": ["delete"], "fields": {}}
        namespace = _build_ns(db, "tags", spec)

        with patch(
            "nomarr.persistence.constructor.namespaces.verbs.delete_by_filter",
            return_value=2,
        ) as mock_delete:
            result = namespace.delete_by_filter({"rel": "genre"})

        assert result == 2
        mock_delete.assert_called_once_with(db, "tags", {"rel": "genre"})

    def test_update_by_filter_attached_when_update_declared(self) -> None:
        """update_by_filter() is attached when collection capabilities include update."""
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": ["update"], "fields": {}}

        namespace = _build_ns(db, "tags", spec)

        assert callable(namespace.update_by_filter)

    def test_update_by_filter_calls_underlying_verb(self) -> None:
        """update_by_filter() delegates to verbs.update_by_filter with both arguments."""
        db = MagicMock()
        spec = {"type": CollectionType.DOCUMENT, "capabilities": ["update"], "fields": {}}
        namespace = _build_ns(db, "tags", spec)

        with patch("nomarr.persistence.constructor.namespaces.verbs.update_by_filter") as mock_update:
            result = namespace.update_by_filter({"rel": "genre"}, {"value": "jazz"})

        assert result is None
        mock_update.assert_called_once_with(db, "tags", {"rel": "genre"}, {"value": "jazz"})


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldNamespaceFilterForwarding:
    """Tests for FieldNamespace collect/aggregate filter forwarding."""

    def test_collect_forwards_filter_kwarg_before_collect_clause(self) -> None:
        """collect() forwards filter and places FILTER before COLLECT in the AQL."""
        db = MagicMock()
        db.aql.execute.return_value = iter(["rock"])
        namespace = FieldNamespace(
            db,
            "tags",
            "value",
            {"type": "str", "capabilities": ["collect"]},
            None,
        )

        result = namespace.collect(filter={"rel": "genre"}, limit=10)

        assert result == ["rock"]
        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        bind_vars = call_args.kwargs["bind_vars"]
        assert "FILTER doc[@f0] == @v0" in aql
        assert "COLLECT val = doc[@field]" in aql
        assert aql.index("FILTER doc[@f0] == @v0") < aql.index("COLLECT val = doc[@field]")
        assert bind_vars == {
            "@col": "tags",
            "field": "value",
            "f0": "rel",
            "v0": "genre",
            "pagination_limit": 10,
        }

    def test_aggregate_forwards_filter_kwarg_before_collect_with_count_clause(self) -> None:
        """aggregate() forwards filter and places FILTER before COLLECT WITH COUNT in the AQL."""
        db = MagicMock()
        db.aql.execute.return_value = iter([{"value": "rock", "count": 2}])
        namespace = FieldNamespace(
            db,
            "tags",
            "value",
            {"type": "str", "capabilities": ["aggregate"]},
            None,
        )

        result = namespace.aggregate(filter={"rel": "genre"}, limit=10)

        assert result == [{"value": "rock", "count": 2}]
        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        bind_vars = call_args.kwargs["bind_vars"]
        assert "FILTER doc[@f0] == @v0" in aql
        assert "COLLECT val = doc[@field] WITH COUNT INTO c" in aql
        assert aql.index("FILTER doc[@f0] == @v0") < aql.index("COLLECT val = doc[@field] WITH COUNT INTO c")
        assert bind_vars == {
            "@col": "tags",
            "field": "value",
            "f0": "rel",
            "v0": "genre",
            "pagination_limit": 10,
        }
