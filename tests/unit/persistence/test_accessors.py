"""Focused tests for persistence field-accessor compatibility shims."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.accessors import CollectionDelete, FieldAccessor
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.collections_base import BaseCollection
from nomarr.persistence.query_specs import QueryOperator, ReadQuerySpec, WriteQuerySpec


def _make_collection() -> BaseCollection:
    db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
    collection = BaseCollection(db, "library_files")
    collection._field("path", unique=True)
    return collection


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldAccessorDelegation:
    """Tests for direct delegation from field shims to collection roots."""

    def test_get_many_delegates_to_collection_root_with_read_query_spec(self) -> None:
        collection = _make_collection()
        collection._collection_get = MagicMock(return_value=[{"_id": "library_files/1"}])  # type: ignore[method-assign]
        accessor = cast("FieldAccessor", collection._fields["path"])

        result = accessor.get.many("/music/a.flac", limit=5, offset=1)

        assert result == [{"_id": "library_files/1"}]
        query_spec = cast("ReadQuerySpec", collection._collection_get.call_args.kwargs["query_spec"])
        assert query_spec.collection_name == "library_files"
        assert query_spec.criteria[0].field_name == "path"
        assert query_spec.criteria[0].operator is QueryOperator.EQ
        assert query_spec.criteria[0].value == "/music/a.flac"
        assert query_spec.pagination.limit == 5
        assert query_spec.pagination.offset == 1
        assert collection._collection_get.call_args.kwargs["force_many"] is True

    def test_delete_in_delegates_to_collection_root_with_write_query_spec(self) -> None:
        collection = _make_collection()
        collection._collection_delete = MagicMock(return_value=2)  # type: ignore[method-assign]
        accessor = cast("FieldAccessor", collection._fields["path"])

        result = accessor.delete.in_(["/music/a.flac", "/music/b.flac"])

        assert result == 2
        query_spec = cast("WriteQuerySpec", collection._collection_delete.call_args.kwargs["query_spec"])
        assert query_spec.collection_name == "library_files"
        assert query_spec.criteria[0].field_name == "path"
        assert query_spec.criteria[0].operator is QueryOperator.IN
        assert query_spec.criteria[0].value == ["/music/a.flac", "/music/b.flac"]


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionDelete:
    """Tests for collection-delete helpers that remain persistence-native."""

    def test_unreferenced_delegates_to_delete_unreferenced_verb(self) -> None:
        collection = _make_collection()
        delete_root = CollectionDelete(collection)

        with patch(
            "nomarr.persistence.constructor.verbs.delete_unreferenced",
            return_value=4,
        ) as delete_unreferenced_mock:
            result = delete_root.unreferenced("file_has_state")

        assert result == 4
        delete_unreferenced_mock.assert_called_once_with(
            collection._db,
            "library_files",
            "file_has_state",
        )
