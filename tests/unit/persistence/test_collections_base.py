"""Unit tests for persistence collection base wrappers."""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar, cast
from unittest.mock import MagicMock, patch

import pytest

import nomarr.persistence.collections_base as collections_base
from nomarr.persistence.accessors import CollectionDelete, CollectionGet, FieldAccessor
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.base_types import CASCADE, OUTBOUND, EdgeDef
from nomarr.persistence.collections import LibraryFiles
from nomarr.persistence.query_specs import (
    AggregateQuerySpec,
    PaginationSpec,
    QueryCriterion,
    QueryOperator,
    ReadQuerySpec,
    SortDirection,
    SortFieldSpec,
    WriteQuerySpec,
)


def _make_db() -> SafeDatabase:
    return cast("SafeDatabase", MagicMock(spec=SafeDatabase))


@pytest.mark.unit
@pytest.mark.mocked
class TestBaseCollectionInit:
    """Tests for ``BaseCollection`` initialization."""

    def test_stores_db_and_name(self) -> None:
        """BaseCollection stores the database handle and collection name."""
        db = _make_db()

        collection = collections_base.BaseCollection(db, "my_collection")

        assert collection._db is db
        assert collection._name == "my_collection"

    def test_fields_dict_starts_empty(self) -> None:
        """BaseCollection starts with an empty field registry."""
        collection = collections_base.BaseCollection(_make_db(), "my_collection")

        assert collection._fields == {}

    def test_get_is_collection_get_instance(self) -> None:
        """BaseCollection creates a ``CollectionGet`` accessor."""
        collection = collections_base.BaseCollection(_make_db(), "my_collection")

        assert isinstance(collection.get, CollectionGet)

    def test_delete_is_collection_delete_instance(self) -> None:
        """BaseCollection creates a ``CollectionDelete`` accessor."""
        collection = collections_base.BaseCollection(_make_db(), "my_collection")

        assert isinstance(collection.delete, CollectionDelete)


@pytest.mark.unit
@pytest.mark.mocked
class TestBaseCollectionField:
    """Tests for ``BaseCollection._field``."""

    def test_returns_field_accessor(self) -> None:
        """_field returns a ``FieldAccessor`` instance."""
        collection = collections_base.BaseCollection(_make_db(), "my_collection")

        accessor = collection._field("some_field")

        assert isinstance(accessor, FieldAccessor)

    def test_registers_field_in_fields_dict(self) -> None:
        """_field stores the accessor in the field registry."""
        collection = collections_base.BaseCollection(_make_db(), "my_collection")

        accessor = collection._field("some_field")

        assert collection._fields["some_field"] is accessor

    def test_unique_flag_passed_to_accessor(self) -> None:
        """_field forwards the unique flag to the accessor."""
        collection = collections_base.BaseCollection(_make_db(), "my_collection")

        accessor = collection._field("f", unique=True)

        assert accessor._unique is True

    def test_non_unique_by_default(self) -> None:
        """_field defaults to non-unique accessors."""
        collection = collections_base.BaseCollection(_make_db(), "my_collection")

        accessor = collection._field("f")

        assert accessor._unique is False


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldAccessorQueryMetadata:
    """Tests for ``FieldAccessor._query_field_metadata``."""

    def test_returns_field_name_and_unique_true(self) -> None:
        """Field metadata should expose the field name and uniqueness flag."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")
        accessor = collection._field("path", unique=True)

        assert accessor._query_field_metadata() == {"name": "path", "unique": True}

    def test_returns_unique_false_for_non_unique_accessor(self) -> None:
        """Non-unique accessors should report ``unique=False`` in metadata."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")
        accessor = collection._field("artist", unique=False)

        assert accessor._query_field_metadata() == {"name": "artist", "unique": False}


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldAccessorCompatibilityBoundary:
    """Tests documenting the intentionally supported Phase 3 shim surface."""

    def test_exposes_only_supported_field_first_methods(self) -> None:
        """Field access keeps only the normalized compatibility mappings."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")
        accessor = collection._field("path", unique=True)

        assert hasattr(accessor, "get")
        assert hasattr(accessor, "update")
        assert hasattr(accessor, "upsert")
        assert hasattr(accessor, "delete")
        assert hasattr(accessor, "count")
        assert hasattr(accessor, "collect")

        assert not hasattr(accessor, "insert")
        assert not hasattr(accessor, "upsert_batch")
        assert not hasattr(accessor, "count_inbound_connections")
        assert not hasattr(accessor, "count_outbound_connections")


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldAccessorCompatibilityDelegation:
    """Tests for collection-first query-spec delegation from field shims."""

    def test_field_get_call_builds_equality_read_query_spec(self) -> None:
        """Single-value field reads delegate through a collection-first read spec."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")
        collection._collection_get = MagicMock(return_value={"_id": "library_files/1"})  # type: ignore[method-assign]
        accessor = collection._field("path", unique=True)

        result = accessor.get("/music/a.flac")

        assert result == {"_id": "library_files/1"}
        call_kwargs = collection._collection_get.call_args.kwargs
        query_spec = cast("ReadQuerySpec", call_kwargs["query_spec"])
        assert query_spec.collection_name == "library_files"
        assert query_spec.criteria[0].field_name == "path"
        assert query_spec.criteria[0].operator is QueryOperator.EQ
        assert query_spec.criteria[0].value == "/music/a.flac"
        assert query_spec.pagination.limit is None
        assert query_spec.pagination.offset == 0
        assert call_kwargs.get("force_many", False) is False

    @pytest.mark.parametrize(
        ("method_name", "value", "operator"),
        [
            ("many", "/music/a.flac", QueryOperator.EQ),
            ("in_", ["/music/a.flac", "/music/b.flac"], QueryOperator.IN),
            ("gte", 100, QueryOperator.GTE),
            ("lte", 100, QueryOperator.LTE),
            ("like", "%beatles%", QueryOperator.LIKE),
        ],
    )
    def test_supported_multi_document_reads_use_collection_first_specs(
        self,
        method_name: str,
        value: object,
        operator: QueryOperator,
    ) -> None:
        """Supported field-first read shims build normalized read query specs."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")
        collection._collection_get = MagicMock(return_value=[{"_id": "library_files/1"}])  # type: ignore[method-assign]
        accessor = collection._field("path", unique=True)

        result = getattr(accessor.get, method_name)(value)

        assert result == [{"_id": "library_files/1"}]
        call_kwargs = collection._collection_get.call_args.kwargs
        query_spec = cast("ReadQuerySpec", call_kwargs["query_spec"])
        assert query_spec.collection_name == "library_files"
        assert query_spec.criteria[0].field_name == "path"
        assert query_spec.criteria[0].operator is operator
        assert query_spec.criteria[0].value == value
        assert call_kwargs["force_many"] is True

    @pytest.mark.parametrize(
        ("method_name", "value", "operator"),
        [
            ("__call__", "/music/a.flac", QueryOperator.EQ),
            ("in_", ["/music/a.flac", "/music/b.flac"], QueryOperator.IN),
        ],
    )
    def test_field_delete_builds_single_field_write_query_spec(
        self,
        method_name: str,
        value: object,
        operator: QueryOperator,
    ) -> None:
        """Field delete shims delegate through single-field collection-first write specs."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")
        collection._collection_delete = MagicMock(return_value=2)  # type: ignore[method-assign]
        accessor = collection._field("path", unique=True)

        result = getattr(accessor.delete, method_name)(value)

        assert result == 2
        call_kwargs = collection._collection_delete.call_args.kwargs
        query_spec = cast("WriteQuerySpec", call_kwargs["query_spec"])
        assert query_spec.collection_name == "library_files"
        assert query_spec.criteria[0].field_name == "path"
        assert query_spec.criteria[0].operator is operator
        assert query_spec.criteria[0].value == value

    def test_field_update_builds_single_field_write_query_spec(self) -> None:
        """Field update remains a compatibility shim over collection-first update()."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")
        collection.update = MagicMock()  # type: ignore[method-assign]
        accessor = collection._field("path", unique=True)

        accessor.update("/music/a.flac", {"artist": "The Beatles"})

        query_spec = cast("WriteQuerySpec", collection.update.call_args.kwargs["query_spec"])
        assert query_spec.collection_name == "library_files"
        assert query_spec.criteria[0].field_name == "path"
        assert query_spec.criteria[0].operator is QueryOperator.EQ
        assert query_spec.criteria[0].value == "/music/a.flac"
        assert query_spec.payload == {"artist": "The Beatles"}

    def test_field_upsert_builds_single_field_write_query_spec(self) -> None:
        """Field upsert remains a compatibility shim over collection-first upsert()."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")
        collection.upsert = MagicMock(return_value=["library_files/1"])  # type: ignore[method-assign]
        accessor = collection._field("path", unique=True)

        result = accessor.upsert("/music/a.flac", {"artist": "The Beatles"})

        assert result == ["library_files/1"]
        query_spec = cast("WriteQuerySpec", collection.upsert.call_args.kwargs["query_spec"])
        assert query_spec.collection_name == "library_files"
        assert query_spec.criteria[0].field_name == "path"
        assert query_spec.criteria[0].operator is QueryOperator.EQ
        assert query_spec.criteria[0].value == "/music/a.flac"
        assert query_spec.payload == {"artist": "The Beatles"}

    def test_field_count_builds_single_field_count_query_spec(self) -> None:
        """Field count remains a compatibility shim over collection-first count()."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")
        collection.count = MagicMock(return_value=7)  # type: ignore[method-assign]
        accessor = collection._field("artist")

        result = accessor.count("The Beatles")

        assert result == 7
        query_spec = cast("AggregateQuerySpec", collection.count.call_args.kwargs["query_spec"])
        assert query_spec.collection_name == "library_files"
        assert query_spec.criteria[0].field_name == "artist"
        assert query_spec.criteria[0].operator is QueryOperator.EQ
        assert query_spec.criteria[0].value == "The Beatles"

    def test_collect_builds_single_field_aggregate_spec_and_unwraps_values(self) -> None:
        """Collect-like access remains the only supported field-first aggregate shim."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")
        collection.aggregate = MagicMock(return_value=[{"value": "A"}, {"count": 2}, {"value": "B"}])  # type: ignore[method-assign]
        accessor = collection._field("artist")

        result = accessor.collect(limit=5, offset=2)

        assert result == ["A", "B"]
        query_spec = cast("AggregateQuerySpec", collection.aggregate.call_args.kwargs["query_spec"])
        assert query_spec.collection_name == "library_files"
        assert query_spec.aggregate_fields == ("artist",)
        assert query_spec.pagination.limit == 5
        assert query_spec.pagination.offset == 2


@pytest.mark.unit
@pytest.mark.mocked
class TestBaseCollectionQueryMetadata:
    """Tests for ``BaseCollection._query_collection_metadata``."""

    def test_returns_collection_name_family_and_empty_fields_when_no_fields_registered(self) -> None:
        """Base metadata should reflect the declared family and an empty field registry."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")

        assert collection._query_collection_metadata() == {
            "collection_name": "library_files",
            "collection_family": collections_base.BaseCollection.COLLECTION_FAMILY,
            "fields": {},
        }

    def test_includes_registered_fields_with_uniqueness_flags(self) -> None:
        """Registered field accessors should be materialized into field metadata."""
        collection = collections_base.BaseCollection(_make_db(), "library_files")
        collection._field("path", unique=True)
        collection._field("artist")

        assert collection._query_collection_metadata() == {
            "collection_name": "library_files",
            "collection_family": collections_base.BaseCollection.COLLECTION_FAMILY,
            "fields": {
                "path": {"name": "path", "unique": True},
                "artist": {"name": "artist", "unique": False},
            },
        }


@pytest.mark.unit
@pytest.mark.mocked
class TestBaseCollectionConnectionCounts:
    """Tests for ``BaseCollection`` connection-count delegation."""

    def test_count_inbound_connections_delegates_to_verbs(self) -> None:
        collection = collections_base.BaseCollection(_make_db(), "tags")

        with patch(
            "nomarr.persistence.constructor.verbs.count_inbound_connections",
            return_value=[{"tag_id": "tags/1", "count": 2}],
        ) as inbound_mock:
            result = collection.count_inbound_connections(
                "song_has_tags",
                filter_field="_id",
                filter_values=["tags/1"],
                return_field="_id",
                label="tag_id",
                limit=5,
                offset=1,
            )

        assert result == [{"tag_id": "tags/1", "count": 2}]
        inbound_mock.assert_called_once_with(
            collection._db,
            "tags",
            "song_has_tags",
            "_id",
            ["tags/1"],
            return_field="_id",
            label="tag_id",
            limit=5,
            offset=1,
        )

    def test_count_outbound_connections_delegates_to_verbs(self) -> None:
        collection = collections_base.BaseCollection(_make_db(), "tags")

        with patch(
            "nomarr.persistence.constructor.verbs.count_outbound_connections",
            return_value=[{"tag_id": "tags/1", "count": 1}],
        ) as outbound_mock:
            result = collection.count_outbound_connections(
                "tag_model_output",
                filter_field="_id",
                filter_values=["tags/1"],
            )

        assert result == [{"tag_id": "tags/1", "count": 1}]
        outbound_mock.assert_called_once_with(
            collection._db,
            "tags",
            "tag_model_output",
            "_id",
            ["tags/1"],
            return_field="_id",
            label="value",
            limit=None,
            offset=0,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestDocumentCollectionInit:
    """Tests for ``DocumentCollection`` initialization."""

    def test_registers_key_id_rev_fields(self) -> None:
        """DocumentCollection registers the built-in document fields."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")

        assert "_key" in collection._fields
        assert "_id" in collection._fields
        assert "_rev" in collection._fields

    def test_key_and_id_are_unique_fields(self) -> None:
        """_key and _id are registered as unique fields."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")

        assert collection._fields["_key"]._unique is True
        assert collection._fields["_id"]._unique is True

    def test_rev_is_non_unique_field(self) -> None:
        """_rev is registered as a non-unique field."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")

        assert collection._fields["_rev"]._unique is False

    def test_auto_attaches_traversal_from_edges(self) -> None:
        """EDGES definitions become traversal callables on the instance."""

        class RelEdges(collections_base.EdgeCollection):
            _name = "rel_edges"

        class ChildDocs(collections_base.DocumentCollection):
            pass

        class ParentDocs(collections_base.DocumentCollection):
            EDGES: ClassVar[list[EdgeDef]] = [
                EdgeDef(via=RelEdges, direction=OUTBOUND, target=ChildDocs, on_delete=CASCADE)
            ]

        collection = ParentDocs(_make_db(), "parent_docs")

        assert hasattr(collection, "rel_edges")
        assert callable(collection.rel_edges)

    def test_no_traversal_attrs_when_edges_empty(self) -> None:
        """No traversal attributes are attached when EDGES is empty."""

        class EmptyDocs(collections_base.DocumentCollection):
            EDGES: ClassVar[list[EdgeDef]] = []

        collection = EmptyDocs(_make_db(), "empty_docs")

        assert not hasattr(collection, "rel_edges")


@pytest.mark.unit
@pytest.mark.mocked
class TestDocumentCollectionAttachCascade:
    """Tests for ``DocumentCollection._attach_cascade``."""

    def test_cascade_is_none_before_attach(self) -> None:
        """Cascade delete starts unset until attached."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")

        assert collection.delete.cascade is None

    def test_injects_callable_onto_delete_cascade(self) -> None:
        """_attach_cascade stores the provided callable on delete.cascade."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")

        def cascade(starts):
            return len(starts)

        collection._attach_cascade(cascade)

        assert collection.delete.cascade is cascade

    def test_overwrites_prior_cascade(self) -> None:
        """A later _attach_cascade call replaces the previous callable."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")

        def first(starts):
            return 1

        def second(starts):
            return 2

        collection._attach_cascade(first)
        collection._attach_cascade(second)

        assert collection.delete.cascade is second


@pytest.mark.unit
@pytest.mark.mocked
class TestDocumentCollectionTraversal:
    """Tests for ``DocumentCollection.traversal``."""

    def test_returns_callable(self) -> None:
        """traversal returns a callable closure."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")

        traverse = collection.traversal("rel_edges", OUTBOUND)

        assert callable(traverse)

    def test_closure_calls_traversal_by_id(self) -> None:
        """The traversal closure delegates to verbs.traversal_by_id."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")
        traverse = collection.traversal("rel_edges", OUTBOUND)

        with patch(
            "nomarr.persistence.constructor.verbs.traversal_by_id", return_value=[{"_id": "docs/2"}]
        ) as mock_traversal:
            result = traverse("docs/1", limit=5, offset=0)

        assert result == [{"_id": "docs/2"}]
        mock_traversal.assert_called_once_with(
            collection._db,
            "docs",
            "docs/1",
            "rel_edges",
            OUTBOUND,
            limit=5,
            offset=0,
        )

    def test_closure_default_limit_and_offset(self) -> None:
        """The traversal closure applies the default paging arguments."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")
        traverse = collection.traversal("rel_edges", OUTBOUND)

        with patch("nomarr.persistence.constructor.verbs.traversal_by_id", return_value=[]) as mock_traversal:
            traverse("docs/1")

        mock_traversal.assert_called_once_with(
            collection._db,
            "docs",
            "docs/1",
            "rel_edges",
            OUTBOUND,
            limit=None,
            offset=0,
        )

    def test_attaches_by_ids_helper_to_traversal_callable(self) -> None:
        """Traversal callables expose a by_ids helper for batched cross-lookups."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")

        traverse = collection.traversal("rel_edges", OUTBOUND)

        assert hasattr(traverse, "by_ids")
        assert callable(traverse.by_ids)

    def test_by_ids_delegates_to_traversal_by_ids_with_exact_filters(self) -> None:
        """by_ids converts exact-match kwargs into target_filter for the verb layer."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")
        traverse = collection.traversal("rel_edges", OUTBOUND)

        with patch(
            "nomarr.persistence.constructor.verbs.traversal_by_ids",
            return_value=[{"start_id": "docs/1", "v": {"name": "isrc", "value": "ABC"}}],
        ) as mock_traversal:
            result = cast("Any", traverse).by_ids(["docs/1"], name="isrc", limit=4, offset=2)

        assert result == [{"start_id": "docs/1", "v": {"name": "isrc", "value": "ABC"}}]
        mock_traversal.assert_called_once_with(
            collection._db,
            "docs",
            ["docs/1"],
            "rel_edges",
            OUTBOUND,
            limit=4,
            offset=2,
            target_filter={"name": "isrc"},
            target_like_starts_with=None,
            include_edge=False,
        )

    def test_by_ids_delegates_to_traversal_by_ids_with_starts_with_filter(self) -> None:
        """by_ids converts *_starts_with kwargs into target_like_starts_with for the verb layer."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")
        traverse = collection.traversal("rel_edges", OUTBOUND)

        with patch(
            "nomarr.persistence.constructor.verbs.traversal_by_ids",
            return_value=[{"start_id": "docs/1", "v": {"name": "nom:mood", "value": "calm"}}],
        ) as mock_traversal:
            result = cast("Any", traverse).by_ids(["docs/1"], name_starts_with="nom:")

        assert result == [{"start_id": "docs/1", "v": {"name": "nom:mood", "value": "calm"}}]
        mock_traversal.assert_called_once_with(
            collection._db,
            "docs",
            ["docs/1"],
            "rel_edges",
            OUTBOUND,
            limit=None,
            offset=0,
            target_filter=None,
            target_like_starts_with=("name", "nom:"),
            include_edge=False,
        )

    def test_by_ids_forwards_include_edge_flag(self) -> None:
        """by_ids forwards include_edge when callers need traversal edge metadata."""
        collection = collections_base.DocumentCollection(_make_db(), "docs")
        traverse = collection.traversal("rel_edges", OUTBOUND)

        with patch(
            "nomarr.persistence.constructor.verbs.traversal_by_ids",
            return_value=[{"start_id": "docs/1", "e": {"_id": "rel_edges/1"}, "v": {"name": "genre"}}],
        ) as mock_traversal:
            result = cast("Any", traverse).by_ids(["docs/1"], include_edge=True)

        assert result == [{"start_id": "docs/1", "e": {"_id": "rel_edges/1"}, "v": {"name": "genre"}}]
        mock_traversal.assert_called_once_with(
            collection._db,
            "docs",
            ["docs/1"],
            "rel_edges",
            OUTBOUND,
            limit=None,
            offset=0,
            target_filter=None,
            target_like_starts_with=None,
            include_edge=True,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestEdgeCollectionInit:
    """Tests for ``EdgeCollection`` initialization."""

    def test_registers_key_id_from_to_fields(self) -> None:
        """EdgeCollection registers the built-in edge fields."""
        collection = collections_base.EdgeCollection(_make_db(), "rel_edges")

        assert "_key" in collection._fields
        assert "_id" in collection._fields
        assert "_from" in collection._fields
        assert "_to" in collection._fields

    def test_key_and_id_are_unique(self) -> None:
        """_key and _id remain unique on edge collections."""
        collection = collections_base.EdgeCollection(_make_db(), "rel_edges")

        assert collection._fields["_key"]._unique is True
        assert collection._fields["_id"]._unique is True

    def test_from_and_to_are_non_unique(self) -> None:
        """_from and _to are non-unique edge fields."""
        collection = collections_base.EdgeCollection(_make_db(), "rel_edges")

        assert collection._fields["_from"]._unique is False
        assert collection._fields["_to"]._unique is False


@pytest.mark.unit
@pytest.mark.mocked
class TestEdgeCollectionMethods:
    """Tests for ``EdgeCollection`` relationship-native helpers."""

    def test_replace_targets_delegates_to_generic_edge_target_helper(self) -> None:
        """replace_targets should route through the normalized edge mutation helper."""
        collection = collections_base.EdgeCollection(_make_db(), "rel_edges")

        with patch("nomarr.persistence.collections_base._replace_edge_targets") as replace_targets_mock:
            collection.replace_targets(["id1", "id2"], "state/pending", "state/done")

        replace_targets_mock.assert_called_once_with(
            collection._db,
            "rel_edges",
            ["id1", "id2"],
            "state/pending",
            "state/done",
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestVectorCollectionInit:
    """Tests for ``VectorCollection`` initialization."""

    def test_registers_key_id_file_id_vector(self) -> None:
        """VectorCollection registers its expected built-in fields."""
        collection = collections_base.VectorCollection(_make_db(), "vectors")

        assert "_key" in collection._fields
        assert "_id" in collection._fields
        assert "file_id" in collection._fields
        assert "model_suite_hash" in collection._fields
        assert "embed_dim" in collection._fields
        assert "vector" in collection._fields
        assert "vector_n" in collection._fields
        assert "num_segments" in collection._fields
        assert "created_at" in collection._fields

    def test_is_not_document_collection_subclass(self) -> None:
        """VectorCollection does not inherit from DocumentCollection."""
        assert not issubclass(collections_base.VectorCollection, collections_base.DocumentCollection)

    def test_key_and_id_are_unique(self) -> None:
        """VectorCollection keeps _key and _id unique."""
        collection = collections_base.VectorCollection(_make_db(), "vectors")

        assert collection._fields["_key"]._unique is True
        assert collection._fields["_id"]._unique is True


@pytest.mark.unit
@pytest.mark.mocked
class TestVectorCollectionMethods:
    """Tests for ``VectorCollection`` vector-specific helpers."""

    def test_upsert_vector_uses_deterministic_key_and_upserts_edge(self) -> None:
        """upsert_vector writes the vector doc and maintains file->vector edge."""
        collection = collections_base.VectorCollection(_make_db(), "vectors_track_hot__effnet__lib1")
        expected_key = hashlib.sha1(b"library_files/7|suite-1").hexdigest()

        with (
            patch.object(collection, "upsert") as mock_upsert,
            patch("nomarr.persistence.collections_base.internal_ms", return_value=MagicMock(value=1234)),
            patch("nomarr.persistence.constructor.verbs.upsert_file_has_vectors_edge") as mock_upsert_edge,
        ):
            collection.upsert_vector(
                file_id="library_files/7",
                model_suite_hash="suite-1",
                embed_dim=3,
                vector=[3.0, 4.0, 0.0],
                num_segments=5,
            )

        mock_upsert.assert_called_once_with(
            _key=expected_key,
            fields={
                "_key": expected_key,
                "file_id": "library_files/7",
                "model_suite_hash": "suite-1",
                "embed_dim": 3,
                "vector": [3.0, 4.0, 0.0],
                "vector_n": [0.6, 0.8, 0.0],
                "num_segments": 5,
                "created_at": 1234,
            },
        )
        mock_upsert_edge.assert_called_once_with(
            collection._db,
            "library_files/7",
            f"vectors_track_hot__effnet__lib1/{expected_key}",
        )
        collection._db.aql.execute.assert_not_called()

    def test_get_vector_delegates_to_collection_get_with_sorted_query_spec(self) -> None:
        """get_vector should be a compatibility shim over collection-first ``get(...)``."""
        collection = collections_base.VectorCollection(_make_db(), "vectors")
        collection.get = MagicMock(return_value={"file_id": "library_files/1"})

        result = collection.get_vector("library_files/1")

        assert result == {"file_id": "library_files/1"}
        collection.get.assert_called_once()
        query_spec = collection.get.call_args.kwargs["query_spec"]
        assert isinstance(query_spec, ReadQuerySpec)
        assert query_spec.collection_name == "vectors"
        assert query_spec.criteria == (QueryCriterion("file_id", QueryOperator.EQ, "library_files/1"),)
        assert query_spec.sort == (SortFieldSpec("created_at", SortDirection.DESC),)
        assert query_spec.pagination.limit == 1
        assert query_spec.pagination.offset == 0

    def test_get_vectors_by_file_ids_delegates_to_collection_get_in(self) -> None:
        """get_vectors_by_file_ids should delegate to collection-first ``get.in_(...)``."""
        collection = collections_base.VectorCollection(_make_db(), "vectors")
        collection.get.in_ = MagicMock(return_value=[{"file_id": "library_files/1"}])  # type: ignore[method-assign]

        result = collection.get_vectors_by_file_ids(["library_files/1"])

        assert result == [{"file_id": "library_files/1"}]
        collection.get.in_.assert_called_once_with(file_id=["library_files/1"])
        collection._db.aql.execute.assert_not_called()

    def test_ann_search_delegates_to_verbs(self) -> None:
        """ann_search delegates to the vector ANN constructor verb."""
        collection = collections_base.VectorCollection(_make_db(), "vectors")

        with patch(
            "nomarr.persistence.constructor.verbs.ann_search",
            return_value=[{"file_id": "library_files/1", "score": 0.9}],
        ) as mock_ann_search:
            result = collection.ann_search([0.1, 0.2], limit=10, nprobe=7, filter={"genres": "rock"})

        assert result == [{"file_id": "library_files/1", "score": 0.9}]
        mock_ann_search.assert_called_once_with(
            collection._db,
            "vectors",
            [0.1, 0.2],
            10,
            7,
            filter={"genres": "rock"},
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestStateGraphCollectionInit:
    """Tests for ``StateGraphCollection`` initialization."""

    def test_stores_edge_name(self) -> None:
        """StateGraphCollection stores the companion edge collection name."""
        collection = collections_base.StateGraphCollection(_make_db(), "state_nodes", "state_transitions")

        assert collection._edge_name == "state_transitions"

    def test_is_document_collection_subclass(self) -> None:
        """StateGraphCollection inherits from DocumentCollection."""
        assert issubclass(collections_base.StateGraphCollection, collections_base.DocumentCollection)

    def test_inherits_base_fields(self) -> None:
        """StateGraphCollection still registers the document base fields."""
        collection = collections_base.StateGraphCollection(_make_db(), "state_nodes", "state_transitions")

        assert "_key" in collection._fields
        assert "_id" in collection._fields
        assert "_rev" in collection._fields


@pytest.mark.unit
@pytest.mark.mocked
class TestStateGraphCollectionTransition:
    """Tests for ``StateGraphCollection.transition``."""

    def test_calls_generic_edge_target_helper(self) -> None:
        """transition should now be a compatibility shim over edge-target replacement."""
        collection = collections_base.StateGraphCollection(_make_db(), "state_nodes", "state_transitions")

        with patch("nomarr.persistence.collections_base._replace_edge_targets") as replace_targets_mock:
            collection.transition(["id1", "id2"], "pending", "done")

        replace_targets_mock.assert_called_once_with(
            collection._db,
            "state_transitions",
            ["id1", "id2"],
            "pending",
            "done",
        )
        collection._db.aql.execute.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionFirstExecutionBoundary:
    """Tests proving collection roots execute without field-shim dispatch."""

    def test_collection_get_query_spec_uses_collection_root_without_field_get(self) -> None:
        """Collection reads should execute from the collection root, not `FieldAccessor.get`."""
        collection = LibraryFiles(_make_db())
        field_get = MagicMock(side_effect=AssertionError("field accessor get should not execute"))
        collection.path.get = field_get  # type: ignore[method-assign]
        execute_mock = cast("MagicMock", collection._db.aql.execute)
        execute_mock.return_value = iter(
            [
                {"_id": "library_files/1", "path": "/music/a.flac"},
            ]
        )

        result = collection.get(
            query_spec=ReadQuerySpec(
                collection_name="library_files",
                criteria=(
                    QueryCriterion(
                        field_name="path",
                        operator=QueryOperator.EQ,
                        value="/music/a.flac",
                    ),
                ),
                pagination=PaginationSpec(limit=None, offset=0),
            )
        )

        assert result == {"_id": "library_files/1", "path": "/music/a.flac"}
        field_get.assert_not_called()
        execute_mock.assert_called_once()

    def test_collection_delete_query_spec_uses_collection_root_without_field_delete(self) -> None:
        """Collection deletes should execute directly from the collection root."""
        collection = LibraryFiles(_make_db())
        collection.path.delete = MagicMock(side_effect=AssertionError("field accessor delete should not execute"))
        query_spec = WriteQuerySpec(
            collection_name="library_files",
            criteria=(
                QueryCriterion(
                    field_name="path",
                    operator=QueryOperator.EQ,
                    value="/music/a.flac",
                ),
            ),
        )

        with patch("nomarr.persistence.constructor.verbs.delete_by_field", return_value=1) as delete_mock:
            result = collection.delete(query_spec=query_spec)

        assert result == 1
        collection.path.delete.assert_not_called()
        delete_mock.assert_called_once_with(
            collection._db,
            "library_files",
            "path",
            "/music/a.flac",
        )

    def test_collection_count_query_spec_consumes_registered_field_metadata(self) -> None:
        """Collection counts should validate via collection metadata, not field-root execution."""
        collection = LibraryFiles(_make_db())
        field_count = MagicMock(side_effect=AssertionError("field accessor count should not execute"))
        collection.artist.count = field_count  # type: ignore[method-assign]
        execute_mock = cast("MagicMock", collection._db.aql.execute)
        execute_mock.return_value = iter([2])

        result = collection.count(
            query_spec=AggregateQuerySpec(
                collection_name="library_files",
                criteria=(
                    QueryCriterion(
                        field_name="artist",
                        operator=QueryOperator.EQ,
                        value="Boards of Canada",
                    ),
                ),
            )
        )

        assert result == 2
        field_count.assert_not_called()
        execute_mock.assert_called_once()
