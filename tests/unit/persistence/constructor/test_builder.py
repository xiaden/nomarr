"""Tests for typed builder helpers and attached constructor verbs."""

from __future__ import annotations

from typing import Annotated, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.filter_types import Op
from nomarr.persistence.base import (
    CASCADE,
    DETACH,
    OUTBOUND,
    DocumentCollection,
    EdgeCollection,
    EdgeDef,
    Field,
    FieldMarker,
    StateGraphCollection,
    UniqueField,
    VectorCollection,
)
from nomarr.persistence.constructor.builder import (
    Builder,
    FieldAccessor,
    _CollectionDeleteVerb,
    _DeleteVerb,
    _extract_field_marker,
    _GetVerb,
    _make_vector_key,
    _normalize_field_criteria,
    _require_single_criterion,
    _TraversalVerb,
)


@pytest.fixture
def mock_db() -> MagicMock:
    """Provide a mock Arango database handle for builder tests."""
    return MagicMock()


def _make_accessor(mock_db: MagicMock, *, unique: bool = False) -> FieldAccessor:
    """Build a field accessor for a test collection."""
    return FieldAccessor(
        db=mock_db,
        collection_name="items",
        field_name="status",
        python_type=str,
        unique=unique,
    )


@pytest.mark.unit
@pytest.mark.mocked
class TestNormalizeFieldCriteria:
    """Tests for _normalize_field_criteria."""

    def test_positional_field_args_merged_into_dict(self) -> None:
        """Positional Field criteria are normalized into a mapping."""
        assert _normalize_field_criteria(Field("status", "active")) == {"status": "active"}

    def test_kwargs_merged_into_dict(self) -> None:
        """Keyword criteria are normalized into a mapping."""
        assert _normalize_field_criteria(name="foo") == {"name": "foo"}

    def test_positional_and_kwargs_combined(self) -> None:
        """Positional Field values and keyword criteria are merged together."""
        assert _normalize_field_criteria(Field("status", "active"), name="foo") == {
            "status": "active",
            "name": "foo",
        }

    def test_empty_call_returns_empty_dict(self) -> None:
        """An empty call produces an empty criteria mapping."""
        assert _normalize_field_criteria() == {}


@pytest.mark.unit
@pytest.mark.mocked
class TestRequireSingleCriterion:
    """Tests for _require_single_criterion."""

    def test_single_positional_returns_tuple(self) -> None:
        """A single positional Field returns its name/value pair."""
        assert _require_single_criterion(Field("_id", "col/1")) == ("_id", "col/1")

    def test_single_kwarg_returns_tuple(self) -> None:
        """A single keyword criterion returns its name/value pair."""
        assert _require_single_criterion(status="active") == ("status", "active")

    def test_zero_criteria_raises_value_error(self) -> None:
        """An empty criterion list is rejected."""
        with pytest.raises(ValueError, match="Expected exactly one"):
            _require_single_criterion()

    def test_multiple_criteria_raises_value_error(self) -> None:
        """Multiple criteria are rejected for single-field helpers."""
        with pytest.raises(ValueError, match="Expected exactly one"):
            _require_single_criterion(status="active", name="foo")


@pytest.mark.unit
@pytest.mark.mocked
class TestExtractFieldMarker:
    """Tests for _extract_field_marker."""

    def test_annotated_non_unique_returns_type_and_false(self) -> None:
        """Annotated FieldMarker(unique=False) returns the inner type and false."""
        assert _extract_field_marker(Annotated[str, FieldMarker(unique=False)]) == (str, False)

    def test_annotated_unique_returns_type_and_true(self) -> None:
        """Annotated FieldMarker(unique=True) returns the inner type and true."""
        assert _extract_field_marker(Annotated[int, FieldMarker(unique=True)]) == (int, True)

    def test_bare_type_returns_none(self) -> None:
        """Bare Python types are not treated as field markers."""
        assert _extract_field_marker(str) is None

    def test_classvar_returns_none(self) -> None:
        """ClassVar annotations are ignored by field extraction."""
        assert _extract_field_marker(ClassVar[str]) is None

    def test_annotated_without_field_marker_returns_none(self) -> None:
        """Annotated values without FieldMarker metadata are ignored."""
        assert _extract_field_marker(Annotated[str, "not a marker"]) is None


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldAccessor:
    """Tests for FieldAccessor."""

    def test_has_get_verb_attached(self, mock_db: MagicMock) -> None:
        """FieldAccessor attaches a _GetVerb helper."""
        accessor = _make_accessor(mock_db)

        assert isinstance(accessor.get, _GetVerb)

    def test_has_delete_verb_attached(self, mock_db: MagicMock) -> None:
        """FieldAccessor attaches a _DeleteVerb helper."""
        accessor = _make_accessor(mock_db)

        assert isinstance(accessor.delete, _DeleteVerb)

    def test_insert_delegates_to_verbs(self, mock_db: MagicMock) -> None:
        """insert() delegates to constructor.verbs.insert."""
        accessor = _make_accessor(mock_db)
        docs = [{"status": "x"}]

        with patch("nomarr.persistence.constructor.builder.verbs.insert", return_value=["items/1"]) as insert_mock:
            result = accessor.insert(docs)

        assert result == ["items/1"]
        insert_mock.assert_called_once_with(mock_db, "items", docs)

    def test_update_delegates_to_verbs(self, mock_db: MagicMock) -> None:
        """update() delegates field name, value, and fields."""
        accessor = _make_accessor(mock_db)
        fields = {"count": 1}

        with patch("nomarr.persistence.constructor.builder.verbs.update_by_field") as update_mock:
            accessor.update("active", fields)

        update_mock.assert_called_once_with(mock_db, "items", "status", "active", fields)

    def test_upsert_merges_field_and_delegates(self, mock_db: MagicMock) -> None:
        """upsert() merges the lookup field into the outgoing document."""
        accessor = _make_accessor(mock_db)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.upsert_by_field", return_value=["items/1"]
        ) as upsert_mock:
            result = accessor.upsert("active", {"count": 1})

        assert result == ["items/1"]
        upsert_mock.assert_called_once_with(
            mock_db,
            "items",
            "status",
            [{"status": "active", "count": 1}],
        )

    def test_count_delegates_to_verbs(self, mock_db: MagicMock) -> None:
        """count() delegates to count_by_field."""
        accessor = _make_accessor(mock_db)

        with patch("nomarr.persistence.constructor.builder.verbs.count_by_field", return_value=3) as count_mock:
            result = accessor.count("active")

        assert result == 3
        count_mock.assert_called_once_with(mock_db, "items", "status", "active")


@pytest.mark.unit
@pytest.mark.mocked
class TestGetVerb:
    """Tests for _GetVerb."""

    def test_unique_accessor_calls_get_one(self, mock_db: MagicMock) -> None:
        """Unique accessors fetch a single document."""
        accessor = _make_accessor(mock_db, unique=True)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.get_one_by_field",
            return_value={"status": "active"},
        ) as get_one_mock:
            result = accessor.get("val")

        assert result == {"status": "active"}
        get_one_mock.assert_called_once_with(mock_db, "items", "status", "val")

    def test_non_unique_accessor_calls_many(self, mock_db: MagicMock) -> None:
        """Non-unique accessors fall back to the many() helper."""
        accessor = _make_accessor(mock_db, unique=False)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.get_many_by_field",
            return_value=[{"status": "active"}],
        ) as get_many_mock:
            result = accessor.get("val")

        assert result == [{"status": "active"}]
        get_many_mock.assert_called_once_with(
            mock_db,
            "items",
            "status",
            "val",
            limit=None,
            offset=0,
        )

    def test_many_delegates_with_limit_and_offset(self, mock_db: MagicMock) -> None:
        """many() forwards limit and offset to get_many_by_field."""
        accessor = _make_accessor(mock_db)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.get_many_by_field",
            return_value=[{"status": "active"}],
        ) as get_many_mock:
            result = accessor.get.many("val", limit=5, offset=2)

        assert result == [{"status": "active"}]
        get_many_mock.assert_called_once_with(
            mock_db,
            "items",
            "status",
            "val",
            limit=5,
            offset=2,
        )

    def test_in_delegates_to_get_in_by_field(self, mock_db: MagicMock) -> None:
        """in_() forwards the candidate values to get_in_by_field."""
        accessor = _make_accessor(mock_db)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.get_in_by_field",
            return_value=[{"status": "a"}, {"status": "b"}],
        ) as get_in_mock:
            result = accessor.get.in_(["a", "b"])

        assert result == [{"status": "a"}, {"status": "b"}]
        get_in_mock.assert_called_once_with(
            mock_db,
            "items",
            "status",
            ["a", "b"],
            limit=None,
            offset=0,
        )

    def test_gte_delegates_to_get_range_by_field(self, mock_db: MagicMock) -> None:
        """gte() sends an Op.GTE range filter."""
        accessor = _make_accessor(mock_db)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.get_range_by_field",
            return_value=[{"status": "active"}],
        ) as range_mock:
            result = accessor.get.gte(5)

        assert result == [{"status": "active"}]
        range_mock.assert_called_once_with(
            mock_db,
            "items",
            "status",
            {Op.GTE: 5},
            limit=None,
            offset=0,
        )

    def test_lte_delegates_to_get_range_by_field(self, mock_db: MagicMock) -> None:
        """lte() sends an Op.LTE range filter."""
        accessor = _make_accessor(mock_db)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.get_range_by_field",
            return_value=[{"status": "active"}],
        ) as range_mock:
            result = accessor.get.lte(10)

        assert result == [{"status": "active"}]
        range_mock.assert_called_once_with(
            mock_db,
            "items",
            "status",
            {Op.LTE: 10},
            limit=None,
            offset=0,
        )

    def test_like_delegates_to_get_like_by_field(self, mock_db: MagicMock) -> None:
        """like() forwards the pattern to get_like_by_field."""
        accessor = _make_accessor(mock_db)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.get_like_by_field",
            return_value=[{"status": "active"}],
        ) as like_mock:
            result = accessor.get.like("%foo%")

        assert result == [{"status": "active"}]
        like_mock.assert_called_once_with(
            mock_db,
            "items",
            "status",
            "%foo%",
            limit=None,
            offset=0,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestDeleteVerb:
    """Tests for _DeleteVerb."""

    def test_call_delegates_to_delete_by_field(self, mock_db: MagicMock) -> None:
        """Calling delete() delegates to delete_by_field."""
        accessor = _make_accessor(mock_db)

        with patch("nomarr.persistence.constructor.builder.verbs.delete_by_field", return_value=2) as delete_mock:
            result = accessor.delete("val")

        assert result == 2
        delete_mock.assert_called_once_with(mock_db, "items", "status", "val")

    def test_in_delegates_to_delete_in_by_field(self, mock_db: MagicMock) -> None:
        """delete.in_() delegates to delete_in_by_field."""
        accessor = _make_accessor(mock_db)

        with patch("nomarr.persistence.constructor.builder.verbs.delete_in_by_field", return_value=2) as delete_in_mock:
            result = accessor.delete.in_(["a", "b"])

        assert result == 2
        delete_in_mock.assert_called_once_with(mock_db, "items", "status", ["a", "b"])

    def test_cascade_attribute_is_none_by_default(self, mock_db: MagicMock) -> None:
        """Field delete helpers do not have cascade attached automatically."""
        accessor = _make_accessor(mock_db)

        assert accessor.delete.cascade is None


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionDeleteVerb:
    """Tests for _CollectionDeleteVerb."""

    def test_no_criteria_calls_truncate(self, mock_db: MagicMock) -> None:
        """Deleting with no criteria truncates the collection."""
        verb = _CollectionDeleteVerb(mock_db, "items")

        with patch("nomarr.persistence.constructor.builder.verbs.truncate") as truncate_mock:
            result = verb()

        assert result == 0
        truncate_mock.assert_called_once_with(mock_db, "items")

    def test_single_kwarg_calls_delete_by_field(self, mock_db: MagicMock) -> None:
        """A single keyword criterion delegates to delete_by_field."""
        verb = _CollectionDeleteVerb(mock_db, "items")

        with patch("nomarr.persistence.constructor.builder.verbs.delete_by_field", return_value=1) as delete_mock:
            result = verb(status="active")

        assert result == 1
        delete_mock.assert_called_once_with(mock_db, "items", "status", "active")

    def test_single_positional_field_calls_delete_by_field(self, mock_db: MagicMock) -> None:
        """A single positional Field delegates to delete_by_field."""
        verb = _CollectionDeleteVerb(mock_db, "items")

        with patch("nomarr.persistence.constructor.builder.verbs.delete_by_field", return_value=1) as delete_mock:
            result = verb(Field("status", "active"))

        assert result == 1
        delete_mock.assert_called_once_with(mock_db, "items", "status", "active")

    def test_multiple_criteria_calls_delete_by_filter(self, mock_db: MagicMock) -> None:
        """Multiple criteria delegate to delete_by_filter."""
        verb = _CollectionDeleteVerb(mock_db, "items")

        with patch(
            "nomarr.persistence.constructor.builder.verbs.delete_by_filter", return_value=2
        ) as delete_filter_mock:
            result = verb(status="active", name="foo")

        assert result == 2
        delete_filter_mock.assert_called_once_with(mock_db, "items", {"status": "active", "name": "foo"})

    def test_cascade_attribute_is_none_by_default(self, mock_db: MagicMock) -> None:
        """Collection delete helpers start without cascade attached."""
        verb = _CollectionDeleteVerb(mock_db, "items")

        assert verb.cascade is None


@pytest.mark.unit
@pytest.mark.mocked
class TestTraversalVerb:
    """Tests for _TraversalVerb."""

    def test_call_delegates_to_traversal_by_id(self, mock_db: MagicMock) -> None:
        """Calling the traversal verb delegates to traversal_by_id."""
        verb = _TraversalVerb(mock_db, "item_links", OUTBOUND)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.traversal_by_id",
            return_value=[{"_id": "target/1"}],
        ) as traversal_mock:
            result = verb("items/1")

        assert result == [{"_id": "target/1"}]
        traversal_mock.assert_called_once_with(
            mock_db,
            "",
            "items/1",
            "item_links",
            OUTBOUND,
            limit=1000,
        )

    def test_by_ids_delegates_to_traversal_by_ids(self, mock_db: MagicMock) -> None:
        """by_ids() forwards ids, edge name, and direction."""
        verb = _TraversalVerb(mock_db, "item_links", OUTBOUND)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.traversal_by_ids",
            return_value=[{"_id": "target/1"}],
        ) as traversal_mock:
            result = verb.by_ids(["items/1"])

        assert result == [{"_id": "target/1"}]
        traversal_mock.assert_called_once_with(
            mock_db,
            "",
            ["items/1"],
            "item_links",
            OUTBOUND,
            target_filter=None,
            target_like_starts_with=None,
        )

    def test_by_ids_limit_slices_result(self, mock_db: MagicMock) -> None:
        """by_ids() applies client-side slicing when a limit is supplied."""
        verb = _TraversalVerb(mock_db, "item_links", OUTBOUND)
        docs = [{"_id": f"target/{index}"} for index in range(5)]

        with patch(
            "nomarr.persistence.constructor.builder.verbs.traversal_by_ids",
            return_value=docs,
        ):
            result = verb.by_ids(["items/1"], limit=2)

        assert result == docs[:2]

    def test_by_ids_starts_with_filter_extracted(self, mock_db: MagicMock) -> None:
        """*_starts_with filters are translated into target_like_starts_with."""
        verb = _TraversalVerb(mock_db, "item_links", OUTBOUND)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.traversal_by_ids",
            return_value=[],
        ) as traversal_mock:
            verb.by_ids(["x/1"], name_starts_with="foo")

        traversal_mock.assert_called_once_with(
            mock_db,
            "",
            ["x/1"],
            "item_links",
            OUTBOUND,
            target_filter=None,
            target_like_starts_with=("name", "foo"),
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestBuilderConstruct:
    """Tests for Builder.construct."""

    def test_construct_attaches_non_unique_field_accessor(self, mock_db: MagicMock) -> None:
        """Field annotations become non-unique accessors on the instance."""

        class TestItems(DocumentCollection):
            _name = "test_items"
            status: Field[str]

        items = TestItems()

        Builder(mock_db).construct(items)

        assert isinstance(items.status, FieldAccessor)
        assert items.status.unique is False
        assert items.status.collection_name == "test_items"

    def test_construct_attaches_unique_field_accessor(self, mock_db: MagicMock) -> None:
        """UniqueField annotations become unique accessors on the instance."""

        class TestItems(DocumentCollection):
            _name = "test_items"
            title: UniqueField[str]

        items = TestItems()

        Builder(mock_db).construct(items)

        assert isinstance(items.title, FieldAccessor)
        assert items.title.unique is True

    def test_construct_attaches_insert_and_delete(self, mock_db: MagicMock) -> None:
        """construct() attaches collection-level insert and delete helpers."""

        class TestItems(DocumentCollection):
            _name = "test_items"
            status: Field[str]

        items = TestItems()

        Builder(mock_db).construct(items)

        assert callable(items.insert)
        assert isinstance(items.delete, _CollectionDeleteVerb)

    def test_construct_attaches_traversal_for_edge_def(self, mock_db: MagicMock) -> None:
        """DETACH edge definitions still attach traversal helpers."""

        class TestItems(DocumentCollection):
            _name = "test_items"
            status: Field[str]

        class TestTargets(DocumentCollection):
            _name = "test_targets"

        class TestItemsToTargetEdges(EdgeCollection):
            _name = "test_items_to_target_edges"
            FROM_COLLECTION = TestItems
            TO_COLLECTION = TestTargets

        TestItems.EDGES = [
            EdgeDef(
                via=TestItemsToTargetEdges,
                direction=OUTBOUND,
                target=TestTargets,
                on_delete=DETACH,
            ),
        ]

        items = TestItems()

        Builder(mock_db).construct(items)

        assert isinstance(items.test_items_to_target_edges, _TraversalVerb)


@pytest.mark.unit
@pytest.mark.mocked
class TestValidateCascadeDag:
    """Tests for Builder._validate_cascade_dag."""

    def test_valid_dag_does_not_raise(self, mock_db: MagicMock) -> None:
        """The production collection graph is acyclic."""
        Builder(mock_db)

    def test_cycle_raises_value_error(self, mock_db: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """CASCADE cycles are rejected during DAG validation."""
        builder = Builder(mock_db)

        class CycleA:
            _name = "cycle_a"

        class CycleB:
            _name = "cycle_b"

        class CycleABEdge:
            _name = "cycle_ab_edge"

        class CycleBAEdge:
            _name = "cycle_ba_edge"

        CycleA.EDGES = [
            EdgeDef(
                via=CycleABEdge,
                direction=OUTBOUND,
                target=CycleB,
                on_delete=CASCADE,
            ),
        ]
        CycleB.EDGES = [
            EdgeDef(
                via=CycleBAEdge,
                direction=OUTBOUND,
                target=CycleA,
                on_delete=CASCADE,
            ),
        ]

        def fake_iter_subclasses(base_cls: type[object]) -> set[type[object]]:
            if base_cls is DocumentCollection:
                return {CycleA, CycleB}
            return set()

        monkeypatch.setattr("nomarr.persistence.constructor.builder._iter_subclasses", fake_iter_subclasses)

        with pytest.raises(ValueError, match="cycle detected"):
            builder._validate_cascade_dag()


def _make_cascade_source_collection(mock_db: MagicMock) -> DocumentCollection:
    """Construct a document collection with one CASCADE edge for delete tests."""

    class CascadeSource(DocumentCollection):
        _name = "cascade_source"
        title: UniqueField[str]

    class CascadeTarget(DocumentCollection):
        _name = "cascade_target"

    class CascadeEdge(EdgeCollection):
        _name = "cascade_edge_col"
        FROM_COLLECTION = CascadeSource
        TO_COLLECTION = CascadeTarget

    CascadeSource.EDGES = [
        EdgeDef(
            via=CascadeEdge,
            direction=OUTBOUND,
            target=CascadeTarget,
            on_delete=CASCADE,
        )
    ]

    items = CascadeSource()
    Builder(mock_db).construct(items)
    return items


@pytest.mark.unit
@pytest.mark.mocked
class TestBuilderAttachedBaseVerbs:
    """Tests for Builder._attach_base_verbs via construct()."""

    def test_construct_attaches_count_update_many_and_aggregate(self, mock_db: MagicMock) -> None:
        """construct() wires count, update_many, and aggregate collection verbs."""

        class TestItems(DocumentCollection):
            _name = "test_items"
            status: Field[str]

        items = TestItems()

        Builder(mock_db).construct(items)

        with (
            patch("nomarr.persistence.constructor.builder.verbs.count_all", return_value=7) as count_mock,
            patch(
                "nomarr.persistence.constructor.builder.verbs.update_many_by_key",
                return_value=["1"],
            ) as update_many_mock,
            patch(
                "nomarr.persistence.constructor.builder.verbs.aggregate_field",
                return_value=[{"value": "active", "count": 2}],
            ) as aggregate_mock,
        ):
            count_result = items.count()
            update_result = items.update_many([{"_key": "1", "status": "active"}])
            aggregate_result = items.aggregate("status")

        assert count_result == 7
        assert update_result == ["1"]
        assert aggregate_result == [{"value": "active", "count": 2}]
        count_mock.assert_called_once_with(mock_db, "test_items")
        update_many_mock.assert_called_once_with(mock_db, "test_items", [{"_key": "1", "status": "active"}])
        aggregate_mock.assert_called_once_with(
            mock_db,
            "test_items",
            "status",
            filter=None,
            limit=None,
            offset=0,
        )

    def test_construct_attaches_truncate_only_for_edge_collections(self, mock_db: MagicMock) -> None:
        """truncate() is attached for edge collections but not documents."""

        class TestItems(DocumentCollection):
            _name = "test_items"

        class TestEdgeCol(EdgeCollection):
            _name = "test_edge_col"
            FROM_COLLECTION = TestItems
            TO_COLLECTION = TestItems

        docs = TestItems()
        edges = TestEdgeCol()

        builder = Builder(mock_db)
        builder.construct(docs)
        builder.construct(edges)

        assert not hasattr(docs, "truncate")
        assert callable(edges.truncate)

        with patch("nomarr.persistence.constructor.builder.verbs.truncate") as truncate_mock:
            edges.truncate()

        truncate_mock.assert_called_once_with(mock_db, "test_edge_col")

    def test_construct_attaches_vector_verbs_for_hot_tier(self, mock_db: MagicMock) -> None:
        """Hot vector collections receive ANN, get_vector, upsert_vector, and move_collection."""

        class TestVectors(VectorCollection):
            _name = "test_vectors"
            VECTOR_TIER = "hot"
            NAME_PATTERN = "test_vectors_{lib}"

        vectors = TestVectors()

        Builder(mock_db).construct(vectors)

        assert callable(vectors.ann_search)
        assert callable(vectors.get_vector)
        assert callable(vectors.upsert_vector)
        assert callable(vectors.move_collection)

        with (
            patch(
                "nomarr.persistence.constructor.builder.verbs.ann_search",
                return_value=[{"_id": "test_vectors/1"}],
            ) as ann_search_mock,
            patch(
                "nomarr.persistence.constructor.builder.verbs.get_vector",
                return_value=[0.1, 0.2],
            ) as get_vector_mock,
            patch("nomarr.persistence.constructor.builder.verbs.move_collection") as move_collection_mock,
        ):
            ann_result = vectors.ann_search([0.25, 0.75], 5, 8, filter={"file_id": "files/1"})
            vector_result = vectors.get_vector("files/1")
            vectors.move_collection("test_vectors_cold")

        assert ann_result == [{"_id": "test_vectors/1"}]
        assert vector_result == [0.1, 0.2]
        ann_search_mock.assert_called_once_with(
            mock_db,
            "test_vectors",
            [0.25, 0.75],
            5,
            8,
            filter={"file_id": "files/1"},
        )
        get_vector_mock.assert_called_once_with(mock_db, "test_vectors", "files/1")
        move_collection_mock.assert_called_once_with(mock_db, "test_vectors", "test_vectors_cold")

    def test_construct_omits_hot_only_vector_verbs_for_cold_tier(self, mock_db: MagicMock) -> None:
        """Cold vector collections omit upsert_vector and move_collection."""

        class TestColdVectors(VectorCollection):
            _name = "test_vectors_cold"
            VECTOR_TIER = "cold"
            NAME_PATTERN = "test_vectors_{lib}"

        vectors = TestColdVectors()

        Builder(mock_db).construct(vectors)

        assert callable(vectors.ann_search)
        assert callable(vectors.get_vector)
        assert not hasattr(vectors, "upsert_vector")
        assert not hasattr(vectors, "move_collection")


@pytest.mark.unit
@pytest.mark.mocked
class TestBuilderCountCallable:
    """Tests for Builder._build_count_callable via attached collection verb."""

    def test_count_without_criteria_calls_count_all(self, mock_db: MagicMock) -> None:
        """count() with no criteria delegates to count_all."""

        class TestItems(DocumentCollection):
            _name = "test_items"

        items = TestItems()
        Builder(mock_db).construct(items)

        with patch("nomarr.persistence.constructor.builder.verbs.count_all", return_value=42) as count_mock:
            result = items.count()

        assert result == 42
        count_mock.assert_called_once_with(mock_db, "test_items")

    def test_count_with_single_kwarg_calls_count_by_field(self, mock_db: MagicMock) -> None:
        """count() with one kwarg delegates to count_by_field."""

        class TestItems(DocumentCollection):
            _name = "test_items"
            title: Field[str]

        items = TestItems()
        Builder(mock_db).construct(items)

        with patch("nomarr.persistence.constructor.builder.verbs.count_by_field", return_value=3) as count_mock:
            result = items.count(title="hello")

        assert result == 3
        count_mock.assert_called_once_with(mock_db, "test_items", "title", "hello")

    def test_count_with_single_positional_field_calls_count_by_field(self, mock_db: MagicMock) -> None:
        """count() with one positional Field delegates to count_by_field."""

        class TestItems(DocumentCollection):
            _name = "test_items"
            title: Field[str]

        items = TestItems()
        Builder(mock_db).construct(items)

        with patch("nomarr.persistence.constructor.builder.verbs.count_by_field", return_value=5) as count_mock:
            result = items.count(Field("title", "hello"))

        assert result == 5
        count_mock.assert_called_once_with(mock_db, "test_items", "title", "hello")

    def test_count_with_multiple_criteria_calls_count_by_filter(self, mock_db: MagicMock) -> None:
        """count() with multiple criteria delegates to count_by_filter."""

        class TestItems(DocumentCollection):
            _name = "test_items"
            title: Field[str]
            status: Field[str]

        items = TestItems()
        Builder(mock_db).construct(items)

        with patch("nomarr.persistence.constructor.builder.verbs.count_by_filter", return_value=9) as count_mock:
            result = items.count(title="hello", status="active")

        assert result == 9
        count_mock.assert_called_once_with(mock_db, "test_items", {"title": "hello", "status": "active"})


@pytest.mark.unit
@pytest.mark.mocked
class TestBuilderAggregateCallable:
    """Tests for Builder._build_aggregate_callable via attached collection verb."""

    def test_aggregate_forwards_optional_filter_limit_and_offset(self, mock_db: MagicMock) -> None:
        """aggregate() passes field and optional pagination/filter arguments through."""

        class TestItems(DocumentCollection):
            _name = "test_items"

        items = TestItems()
        Builder(mock_db).construct(items)

        with patch(
            "nomarr.persistence.constructor.builder.verbs.aggregate_field",
            return_value=[{"value": "active", "count": 2}],
        ) as aggregate_mock:
            result = items.aggregate("status", filter={"genre": "rock"}, limit=4, offset=2)

        assert result == [{"value": "active", "count": 2}]
        aggregate_mock.assert_called_once_with(
            mock_db,
            "test_items",
            "status",
            filter={"genre": "rock"},
            limit=4,
            offset=2,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestBuilderUpsertVectorCallable:
    """Tests for Builder._build_upsert_vector_callable."""

    def test_upsert_vector_normalizes_vector_and_links_edge(self, mock_db: MagicMock) -> None:
        """upsert_vector() stores both raw and normalized vectors and links the file edge."""

        class TestVectors(VectorCollection):
            _name = "test_vectors"
            VECTOR_TIER = "hot"
            NAME_PATTERN = "test_vectors_{lib}"

        vectors = TestVectors()
        Builder(mock_db).construct(vectors)

        timestamp = MagicMock(value=123456789)

        with (
            patch("nomarr.persistence.constructor.builder.now_ms", return_value=timestamp),
            patch("nomarr.persistence.constructor.builder.verbs.upsert_by_field") as upsert_mock,
            patch("nomarr.persistence.constructor.builder.verbs.upsert_file_has_vectors_edge") as edge_mock,
        ):
            vectors.upsert_vector("files/1", "suite_hash", 2, [3.0, 4.0], 7)

        expected_key = _make_vector_key("files/1", "suite_hash")
        upsert_args = upsert_mock.call_args.args
        [doc] = upsert_args[3]

        assert upsert_args[:3] == (mock_db, "test_vectors", "_key")
        assert doc["_key"] == expected_key
        assert doc["file_id"] == "files/1"
        assert doc["model_suite_hash"] == "suite_hash"
        assert doc["embed_dim"] == 2
        assert doc["vector"] == [3.0, 4.0]
        assert doc["vector_n"] == pytest.approx([0.6, 0.8])
        assert doc["num_segments"] == 7
        assert doc["created_at"] == 123456789
        edge_mock.assert_called_once_with(mock_db, "files/1", f"test_vectors/{expected_key}")

    def test_upsert_vector_keeps_zero_norm_vector_unchanged(self, mock_db: MagicMock) -> None:
        """Zero-norm vectors use the original values for vector_n instead of dividing by zero."""

        class TestVectors(VectorCollection):
            _name = "test_vectors"
            VECTOR_TIER = "hot"
            NAME_PATTERN = "test_vectors_{lib}"

        vectors = TestVectors()
        Builder(mock_db).construct(vectors)

        timestamp = MagicMock(value=987654321)

        with (
            patch("nomarr.persistence.constructor.builder.now_ms", return_value=timestamp),
            patch("nomarr.persistence.constructor.builder.verbs.upsert_by_field") as upsert_mock,
            patch("nomarr.persistence.constructor.builder.verbs.upsert_file_has_vectors_edge") as edge_mock,
        ):
            vectors.upsert_vector("files/2", "suite_hash", 2, [0.0, 0.0], 1)

        expected_key = _make_vector_key("files/2", "suite_hash")
        [doc] = upsert_mock.call_args.args[3]

        assert doc["vector"] == [0.0, 0.0]
        assert doc["vector_n"] == [0.0, 0.0]
        edge_mock.assert_called_once_with(mock_db, "files/2", f"test_vectors/{expected_key}")


@pytest.mark.unit
@pytest.mark.mocked
class TestBuilderCascadeAttachment:
    """Tests for Builder._attach_cascade via construct()."""

    def test_construct_attaches_cascade_to_collection_and_key_accessors(self, mock_db: MagicMock) -> None:
        """construct() attaches cascade delete to collection, _key, and _id delete helpers."""
        items = _make_cascade_source_collection(mock_db)

        assert callable(items.delete.cascade)
        assert callable(items._key.delete.cascade)
        assert callable(items._id.delete.cascade)

    def test_cascade_delete_by_id_executes_aql_without_lookup(self, mock_db: MagicMock) -> None:
        """Deleting by _id skips lookup and runs the precompiled cascade AQL directly."""
        items = _make_cascade_source_collection(mock_db)

        with (
            patch(
                "nomarr.persistence.constructor.builder.verbs._execute_aql",
                return_value=iter([]),
            ) as aql_mock,
            patch("nomarr.persistence.constructor.builder.verbs.get_one_by_field") as get_one_mock,
        ):
            result = items.delete.cascade(_id="cascade_source/1")

        assert result == 1
        get_one_mock.assert_not_called()
        aql_mock.assert_called_once()
        assert aql_mock.call_args.kwargs["bind_vars"] == {"start": "cascade_source/1"}

    def test_cascade_delete_by_field_looks_up_document_before_running_aql(self, mock_db: MagicMock) -> None:
        """Deleting by another field resolves the start _id before executing AQL."""
        items = _make_cascade_source_collection(mock_db)

        with (
            patch(
                "nomarr.persistence.constructor.builder.verbs.get_one_by_field",
                return_value={"_id": "cascade_source/42"},
            ) as get_one_mock,
            patch(
                "nomarr.persistence.constructor.builder.verbs._execute_aql",
                return_value=iter([]),
            ) as aql_mock,
        ):
            result = items.delete.cascade(title="The Title")

        assert result == 1
        get_one_mock.assert_called_once_with(mock_db, "cascade_source", "title", "The Title")
        aql_mock.assert_called_once()
        assert aql_mock.call_args.kwargs["bind_vars"] == {"start": "cascade_source/42"}

    def test_cascade_delete_returns_zero_when_lookup_finds_no_document(self, mock_db: MagicMock) -> None:
        """Deleting by another field returns 0 when the source document is not found."""
        items = _make_cascade_source_collection(mock_db)

        with (
            patch("nomarr.persistence.constructor.builder.verbs.get_one_by_field", return_value=None) as get_one_mock,
            patch("nomarr.persistence.constructor.builder.verbs._execute_aql") as aql_mock,
        ):
            result = items.delete.cascade(title="Missing")

        assert result == 0
        get_one_mock.assert_called_once_with(mock_db, "cascade_source", "title", "Missing")
        aql_mock.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
class TestBuilderStateGraphAttachment:
    """Tests for Builder._attach_state_graph via construct()."""

    def test_construct_attaches_transition_for_state_graph_with_edges(self, mock_db: MagicMock) -> None:
        """State graph collections with edges receive a working transition helper."""

        class WorkflowTarget(DocumentCollection):
            _name = "workflow_target"

        class WorkflowState(StateGraphCollection):
            _name = "workflow_state"

        class WorkflowStateEdge(EdgeCollection):
            _name = "workflow_state_edge"
            FROM_COLLECTION = WorkflowState
            TO_COLLECTION = WorkflowTarget

        WorkflowState.EDGES = [
            EdgeDef(
                via=WorkflowStateEdge,
                direction=OUTBOUND,
                target=WorkflowTarget,
                on_delete=DETACH,
            )
        ]

        states = WorkflowState()
        Builder(mock_db).construct(states)

        assert callable(states.transition)

        with patch("nomarr.persistence.constructor.builder.verbs.transition", return_value=2) as transition_mock:
            result = states.transition(["files/1"], "queued", "done")

        assert result == 2
        transition_mock.assert_called_once_with(
            mock_db,
            "workflow_state_edge",
            ["files/1"],
            "queued",
            "done",
        )

    def test_construct_skips_transition_for_state_graph_without_edges(self, mock_db: MagicMock) -> None:
        """State graph collections without edges do not get a transition helper."""

        class EmptyStateGraph(StateGraphCollection):
            _name = "empty_state_graph"

        states = EmptyStateGraph()
        Builder(mock_db).construct(states)

        assert not hasattr(states, "transition")


@pytest.mark.unit
@pytest.mark.mocked
class TestBuilderCascadeQueryHelpers:
    """Tests for cascade query compilation and edge discovery helpers."""

    def test_compile_cascade_query_returns_expected_aql_fragments(self, mock_db: MagicMock) -> None:
        """Compiled cascade AQL includes the traversal, edge collection, and root delete."""

        class CascadeSource(DocumentCollection):
            _name = "cascade_source"

        class CascadeTarget(DocumentCollection):
            _name = "cascade_target"

        class CascadeEdge(EdgeCollection):
            _name = "cascade_edge_col"
            FROM_COLLECTION = CascadeSource
            TO_COLLECTION = CascadeTarget

        edge_def = EdgeDef(
            via=CascadeEdge,
            direction=OUTBOUND,
            target=CascadeTarget,
            on_delete=CASCADE,
        )
        CascadeSource.EDGES = [edge_def]

        query = Builder(mock_db)._compile_cascade_query(CascadeSource, "cascade_source", [edge_def])

        assert isinstance(query, str)
        assert "LET subgraph" in query
        assert "cascade_edge_col" in query
        assert "REMOVE PARSE_IDENTIFIER(@start).key IN cascade_source" in query

    def test_cascade_edge_names_for_root_returns_single_cascade_edge(self, mock_db: MagicMock) -> None:
        """A single cascade edge contributes one edge collection name."""

        class CascadeSource(DocumentCollection):
            _name = "cascade_source"

        class CascadeTarget(DocumentCollection):
            _name = "cascade_target"

        class CascadeEdge(EdgeCollection):
            _name = "cascade_edge_col"
            FROM_COLLECTION = CascadeSource
            TO_COLLECTION = CascadeTarget

        CascadeSource.EDGES = [
            EdgeDef(
                via=CascadeEdge,
                direction=OUTBOUND,
                target=CascadeTarget,
                on_delete=CASCADE,
            )
        ]

        names = Builder(mock_db)._cascade_edge_names_for_root(CascadeSource)

        assert names == ["cascade_edge_col"]

    def test_cascade_edge_names_for_root_excludes_detach_edges(self, mock_db: MagicMock) -> None:
        """DETACH edges are ignored when collecting cascade edge names."""

        class CascadeSource(DocumentCollection):
            _name = "cascade_source"

        class CascadeTarget(DocumentCollection):
            _name = "cascade_target"

        class DetachEdge(EdgeCollection):
            _name = "detach_edge_col"
            FROM_COLLECTION = CascadeSource
            TO_COLLECTION = CascadeTarget

        CascadeSource.EDGES = [
            EdgeDef(
                via=DetachEdge,
                direction=OUTBOUND,
                target=CascadeTarget,
                on_delete=DETACH,
            )
        ]

        names = Builder(mock_db)._cascade_edge_names_for_root(CascadeSource)

        assert names == []

    def test_cascade_edge_names_for_root_returns_nested_cascade_edges_in_order(self, mock_db: MagicMock) -> None:
        """Nested cascade edges are returned in discovery order from root to leaf."""

        class Root(DocumentCollection):
            _name = "root"

        class Middle(DocumentCollection):
            _name = "middle"

        class Leaf(DocumentCollection):
            _name = "leaf"

        class RootToMiddleEdge(EdgeCollection):
            _name = "root_to_middle_edge"
            FROM_COLLECTION = Root
            TO_COLLECTION = Middle

        class MiddleToLeafEdge(EdgeCollection):
            _name = "middle_to_leaf_edge"
            FROM_COLLECTION = Middle
            TO_COLLECTION = Leaf

        Middle.EDGES = [
            EdgeDef(
                via=MiddleToLeafEdge,
                direction=OUTBOUND,
                target=Leaf,
                on_delete=CASCADE,
            )
        ]
        Root.EDGES = [
            EdgeDef(
                via=RootToMiddleEdge,
                direction=OUTBOUND,
                target=Middle,
                on_delete=CASCADE,
            )
        ]

        names = Builder(mock_db)._cascade_edge_names_for_root(Root)

        assert names == ["root_to_middle_edge", "middle_to_leaf_edge"]
