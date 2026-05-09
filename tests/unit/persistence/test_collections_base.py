"""Unit tests for persistence collection base wrappers."""

from __future__ import annotations

import hashlib
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

import nomarr.persistence.collections_base as collections_base
from nomarr.persistence.accessors import CollectionDelete, CollectionGet, FieldAccessor
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.base_types import CASCADE, OUTBOUND, EdgeDef


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
class TestBaseCollectionConnectionCounts:
    """Tests for ``BaseCollection`` connection-count delegation."""

    def test_count_inbound_connections_delegates_to_verbs(self) -> None:
        collection = collections_base.BaseCollection(_make_db(), "tags")

        with patch(
            "nomarr.persistence.collections_base.verbs.count_inbound_connections",
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
            "nomarr.persistence.collections_base.verbs.count_outbound_connections",
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
            EDGES = (EdgeDef(via=RelEdges, direction=OUTBOUND, target=ChildDocs, on_delete=CASCADE),)

        collection = ParentDocs(_make_db(), "parent_docs")

        assert hasattr(collection, "rel_edges")
        assert callable(collection.rel_edges)

    def test_no_traversal_attrs_when_edges_empty(self) -> None:
        """No traversal attributes are attached when EDGES is empty."""

        class EmptyDocs(collections_base.DocumentCollection):
            EDGES = ()

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
            "nomarr.persistence.collections_base.verbs.traversal_by_id", return_value=[{"_id": "docs/2"}]
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

        with patch("nomarr.persistence.collections_base.verbs.traversal_by_id", return_value=[]) as mock_traversal:
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
            "nomarr.persistence.collections_base.verbs.traversal_by_ids",
            return_value=[{"start_id": "docs/1", "v": {"name": "isrc", "value": "ABC"}}],
        ) as mock_traversal:
            result = traverse.by_ids(["docs/1"], name="isrc", limit=4, offset=2)

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
            "nomarr.persistence.collections_base.verbs.traversal_by_ids",
            return_value=[{"start_id": "docs/1", "v": {"name": "nom:mood", "value": "calm"}}],
        ) as mock_traversal:
            result = traverse.by_ids(["docs/1"], name_starts_with="nom:")

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
            "nomarr.persistence.collections_base.verbs.traversal_by_ids",
            return_value=[{"start_id": "docs/1", "e": {"_id": "rel_edges/1"}, "v": {"name": "genre"}}],
        ) as mock_traversal:
            result = traverse.by_ids(["docs/1"], include_edge=True)

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
            patch("nomarr.persistence.collections_base.verbs.upsert_file_has_vectors_edge") as mock_upsert_edge,
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

    def test_get_vector_delegates_to_verbs(self) -> None:
        """get_vector delegates to the constructor verb for latest-vector lookup."""
        collection = collections_base.VectorCollection(_make_db(), "vectors")

        with patch(
            "nomarr.persistence.collections_base.verbs.get_vector",
            return_value={"file_id": "library_files/1"},
        ) as mock_get_vector:
            result = collection.get_vector("library_files/1")

        assert result == {"file_id": "library_files/1"}
        mock_get_vector.assert_called_once_with(collection._db, "vectors", "library_files/1")

    def test_ann_search_delegates_to_verbs(self) -> None:
        """ann_search delegates to the vector ANN constructor verb."""
        collection = collections_base.VectorCollection(_make_db(), "vectors")

        with patch(
            "nomarr.persistence.collections_base.verbs.ann_search",
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

    def test_calls_verbs_transition(self) -> None:
        """transition delegates to verbs.transition with the stored edge name."""
        collection = collections_base.StateGraphCollection(_make_db(), "state_nodes", "state_transitions")

        with patch("nomarr.persistence.collections_base.verbs.transition") as mock_transition:
            collection.transition(["id1", "id2"], "pending", "done")

        mock_transition.assert_called_once_with(
            collection._db,
            "state_transitions",
            ["id1", "id2"],
            "pending",
            "done",
        )
