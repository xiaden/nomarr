"""Unit tests for persistence accessor compatibility shims."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.accessors import CollectionDelete, CollectionGet, FieldAccessor
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.base_types import Field
from nomarr.persistence.query_specs import (
    AggregateQuerySpec,
    QueryCriterion,
    QueryOperator,
    ReadQuerySpec,
    WriteQuerySpec,
)


class _OwnerStub:
    """Minimal owner implementing the collection-first accessor protocol for tests."""

    def __init__(self, *, name: str = "docs") -> None:
        self._db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        self._name = name
        self._collection_get = MagicMock(name="_collection_get")
        self._collection_delete = MagicMock(name="_collection_delete")
        self.update = MagicMock(name="update")
        self.upsert = MagicMock(name="upsert")
        self.count = MagicMock(name="count")
        self.aggregate = MagicMock(name="aggregate")
        self.count_inbound_connections = MagicMock(name="count_inbound_connections")
        self.count_outbound_connections = MagicMock(name="count_outbound_connections")


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldAccessor:
    """Tests for ``FieldAccessor``."""

    def test_constructor_builds_field_specific_get_and_delete_helpers(self) -> None:
        owner = _OwnerStub(name="library_files")

        accessor = FieldAccessor(owner, "path", unique=True)

        assert accessor._db is owner._db
        assert accessor._collection == "library_files"
        assert accessor._field == "path"
        assert accessor._unique is True
        assert accessor.get._field == "path"
        assert accessor.delete._field == "path"

    def test_upsert_builds_field_query_spec_and_delegates_to_owner(self) -> None:
        owner = _OwnerStub(name="library_files")
        owner.upsert.return_value = ["doc-1"]
        accessor = FieldAccessor(owner, "path")

        result = accessor.upsert("song.flac", {"size": 123})

        assert result == ["doc-1"]
        owner.upsert.assert_called_once()
        query_spec = owner.upsert.call_args.kwargs["query_spec"]
        assert isinstance(query_spec, WriteQuerySpec)
        assert query_spec.collection_name == "library_files"
        assert query_spec.payload == {"size": 123}
        assert query_spec.criteria == (QueryCriterion("path", QueryOperator.EQ, "song.flac"),)

    def test_count_builds_field_count_query_spec(self) -> None:
        owner = _OwnerStub(name="tags")
        owner.count.return_value = 4
        accessor = FieldAccessor(owner, "name")

        result = accessor.count("genre")

        assert result == 4
        owner.count.assert_called_once()
        query_spec = owner.count.call_args.kwargs["query_spec"]
        assert isinstance(query_spec, AggregateQuerySpec)
        assert query_spec.collection_name == "tags"
        assert query_spec.criteria == (QueryCriterion("name", QueryOperator.EQ, "genre"),)

    def test_collect_extracts_value_column_from_collection_aggregate_rows(self) -> None:
        owner = _OwnerStub(name="tags")
        owner.aggregate.return_value = [{"value": "rock"}, {"value": "jazz"}, {"other": "ignored"}]
        accessor = FieldAccessor(owner, "name")

        result = accessor.collect(limit=5, offset=2)

        assert result == ["rock", "jazz"]
        owner.aggregate.assert_called_once()
        query_spec = owner.aggregate.call_args.kwargs["query_spec"]
        assert isinstance(query_spec, AggregateQuerySpec)
        assert query_spec.collection_name == "tags"
        assert query_spec.aggregate_fields == ("name",)
        assert query_spec.pagination.limit == 5
        assert query_spec.pagination.offset == 2


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionGet:
    """Tests for ``CollectionGet`` dispatch behavior."""

    def test_call_delegates_to_owner_collection_get(self) -> None:
        owner = _OwnerStub()
        owner._collection_get.return_value = {"_key": "doc-1"}
        collection_get = CollectionGet(owner)

        result = collection_get(slug="alpha", limit=10, offset=3)

        assert result == {"_key": "doc-1"}
        owner._collection_get.assert_called_once_with(limit=10, offset=3, criteria=None, query_spec=None, slug="alpha")

    def test_many_forces_list_result(self) -> None:
        owner = _OwnerStub()
        owner._collection_get.return_value = [{"_key": "doc-2"}]
        collection_get = CollectionGet(owner)

        result = collection_get.many(status="ready", limit=4, offset=1)

        assert result == [{"_key": "doc-2"}]
        owner._collection_get.assert_called_once_with(
            limit=4,
            offset=1,
            criteria=None,
            query_spec=None,
            force_many=True,
            status="ready",
        )

    def test_in_builds_read_query_spec(self) -> None:
        owner = _OwnerStub()
        owner._collection_get.return_value = [{"_key": "doc-5"}]
        collection_get = CollectionGet(owner)

        result = collection_get.in_(Field("slug", ["a", "b"]), limit=8, offset=2)

        assert result == [{"_key": "doc-5"}]
        owner._collection_get.assert_called_once()
        query_spec = owner._collection_get.call_args.kwargs["query_spec"]
        assert isinstance(query_spec, ReadQuerySpec)
        assert query_spec.collection_name == "docs"
        assert query_spec.criteria == (QueryCriterion("slug", QueryOperator.IN, ["a", "b"]),)
        assert query_spec.pagination.limit == 8
        assert query_spec.pagination.offset == 2
        assert owner._collection_get.call_args.kwargs["force_many"] is True

    def test_in_requires_exactly_one_criterion(self) -> None:
        collection_get = CollectionGet(_OwnerStub())

        with pytest.raises(ValueError, match="exactly one criterion"):
            collection_get.in_(Field("slug", ["a"]), Field("status", ["ready"]))


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionDelete:
    """Tests for ``CollectionDelete`` dispatch behavior."""

    def test_call_delegates_to_owner_collection_delete(self) -> None:
        owner = _OwnerStub()
        owner._collection_delete.return_value = 3
        collection_delete = CollectionDelete(owner)

        result = collection_delete(slug="alpha")

        assert result == 3
        owner._collection_delete.assert_called_once_with(criteria=None, query_spec=None, slug="alpha")

    def test_in_builds_write_query_spec(self) -> None:
        owner = _OwnerStub()
        owner._collection_delete.return_value = 2
        collection_delete = CollectionDelete(owner)

        result = collection_delete.in_(Field("slug", ["a", "b"]))

        assert result == 2
        owner._collection_delete.assert_called_once()
        query_spec = owner._collection_delete.call_args.kwargs["query_spec"]
        assert isinstance(query_spec, WriteQuerySpec)
        assert query_spec.collection_name == "docs"
        assert query_spec.criteria == (QueryCriterion("slug", QueryOperator.IN, ["a", "b"]),)

    def test_in_requires_exactly_one_criterion(self) -> None:
        collection_delete = CollectionDelete(_OwnerStub())

        with pytest.raises(ValueError, match="exactly one criterion"):
            collection_delete.in_(Field("slug", ["a"]), Field("status", ["ready"]))

    def test_unreferenced_calls_delete_unreferenced(self) -> None:
        owner = _OwnerStub()
        collection_delete = CollectionDelete(owner)

        with patch(
            "nomarr.persistence.constructor.verbs.delete_unreferenced", return_value=4
        ) as delete_unreferenced_mock:
            result = collection_delete.unreferenced("doc_edges")

        assert result == 4
        delete_unreferenced_mock.assert_called_once_with(owner._db, "docs", "doc_edges")

    def test_cascade_property_defaults_to_none(self) -> None:
        collection_delete = CollectionDelete(_OwnerStub())

        assert collection_delete.cascade is None
