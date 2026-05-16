from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase

pytestmark = pytest.mark.unit


class DummyDatabase:
    def __init__(
        self,
        *,
        cursor_rows: list[Any] | None = None,
        insert_result: dict[str, Any] | None = None,
    ) -> None:
        self.aql = MagicMock()
        self.aql.execute = MagicMock(return_value=iter(cursor_rows or []))
        self._collection = MagicMock()
        self._collection.insert = MagicMock(return_value=insert_result or {"_id": "libraries/abc"})
        self.collection = MagicMock(return_value=self._collection)


def make_db(
    *,
    cursor_rows: list[Any] | None = None,
    insert_result: dict[str, Any] | None = None,
) -> DummyDatabase:
    return DummyDatabase(cursor_rows=cursor_rows, insert_result=insert_result)


def as_safe_db(db: DummyDatabase) -> SafeDatabase:
    return cast("SafeDatabase", db)


def test_validate_field_name_accepts_expected_names() -> None:
    for field_name in ("foo", "bar_baz", "field123", "nested.path", "A1_b.c"):
        primitives._validate_field_name(field_name)


@pytest.mark.parametrize(
    "field_name",
    ["", ".bad", "_bad", "contains space", "dash-name", "$money", "weird/slash"],
)
def test_validate_field_name_rejects_invalid_names(field_name: str) -> None:
    with pytest.raises(ValueError):
        primitives._validate_field_name(field_name)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (-1, None), (0, None), (7, 7)],
)
def test_normalize_limit(value: int | None, expected: int | None) -> None:
    assert primitives.normalize_limit(value) == expected


def test_execute_materializes_cursor_and_forwards_bind_vars() -> None:
    db = make_db(cursor_rows=[{"_key": "a"}, {"_key": "b"}])

    result = primitives.execute(as_safe_db(db), "RETURN @value", {"value": 1})

    assert result == [{"_key": "a"}, {"_key": "b"}]
    db.aql.execute.assert_called_once_with("RETURN @value", bind_vars={"value": 1})


def test_get_many_by_keys_uses_collection_bind_var_and_key_list() -> None:
    db = make_db(cursor_rows=[{"_key": "abc"}])

    result = primitives.get_many_by_keys(as_safe_db(db), "libraries", ["abc", "def"])

    assert result == [{"_key": "abc"}]
    call = db.aql.execute.call_args
    assert call is not None
    assert "FOR doc IN @@collection" in call.args[0]
    assert "doc._key IN @keys" in call.args[0]
    assert call.kwargs["bind_vars"] == {"@collection": "libraries", "keys": ["abc", "def"]}


def test_get_many_by_field_rejects_unknown_field() -> None:
    db = make_db()

    with pytest.raises(ValueError):
        primitives.get_many_by_field(
            as_safe_db(db),
            "libraries",
            "forbidden",
            "value",
            limit=1,
            allowed_fields={"name"},
        )


def test_get_filtered_docs_builds_multi_filter_query() -> None:
    db = make_db(cursor_rows=[{"name": "alpha"}])

    result = primitives.get_filtered_docs(
        as_safe_db(db),
        "libraries",
        filters={"name": "alpha", "watch_mode": "poll"},
        sort_field="name",
        limit=10,
        allowed_fields={"name", "watch_mode"},
    )

    assert result == [{"name": "alpha"}]
    call = db.aql.execute.call_args
    assert call is not None
    query = call.args[0]
    assert "FILTER doc.name == @filter_0" in query or "FILTER doc.watch_mode == @filter_0" in query
    assert "SORT doc.name" in query
    assert "LIMIT @limit" in query
    assert call.kwargs["bind_vars"]["limit"] == 10


def test_delete_many_by_field_returns_removed_count_for_scalar_filter() -> None:
    db = make_db(cursor_rows=[2])

    result = primitives.delete_many_by_field(
        as_safe_db(db),
        "libraries",
        "name",
        "Main",
        allowed_fields={"name"},
    )

    assert result == 2
    assert isinstance(result, int)
    call = db.aql.execute.call_args
    assert call is not None
    assert "FILTER doc.name == @field_value" in call.args[0]
    assert "REMOVE doc IN @@collection" in call.args[0]
    assert call.kwargs["bind_vars"] == {"@collection": "libraries", "field_value": "Main"}


def test_delete_many_by_field_uses_in_filter_for_list_values() -> None:
    db = make_db(cursor_rows=[3])

    result = primitives.delete_many_by_field(
        as_safe_db(db),
        "libraries",
        "name",
        ["Main", "Side"],
        allowed_fields={"name"},
    )

    assert result == 3
    assert isinstance(result, int)
    call = db.aql.execute.call_args
    assert call is not None
    assert "FILTER doc.name IN @field_value" in call.args[0]
    assert call.kwargs["bind_vars"] == {"@collection": "libraries", "field_value": ["Main", "Side"]}


@pytest.mark.unit
@pytest.mark.mocked
def test_delete_many_by_field_query_includes_ignore_errors_option() -> None:
    db = make_db(cursor_rows=[1])

    primitives.delete_many_by_field(
        as_safe_db(db),
        "libraries",
        "name",
        "Main",
        allowed_fields={"name"},
    )

    call = db.aql.execute.call_args
    assert call is not None
    assert "OPTIONS { ignoreErrors: true }" in call.args[0]


def test_delete_many_by_field_returns_zero_for_empty_list_without_query() -> None:
    db = make_db(cursor_rows=[99])

    result = primitives.delete_many_by_field(
        as_safe_db(db),
        "libraries",
        "name",
        [],
        allowed_fields={"name"},
    )

    assert result == 0
    db.aql.execute.assert_not_called()


def test_count_distinct_edge_sources_to_filtered_vertices_unwraps_integer() -> None:
    db = make_db(cursor_rows=[4])

    result = primitives.count_distinct_edge_sources_to_filtered_vertices(
        as_safe_db(db),
        edge_collection="song_has_tags",
        vertex_collection="tags",
        vertex_filters={"name": "nom:mood", "value": "calm"},
    )

    assert result == 4
    call = db.aql.execute.call_args
    assert call is not None
    assert call.kwargs["bind_vars"]["@edge_collection"] == "song_has_tags"
    assert call.kwargs["bind_vars"]["@vertex_collection"] == "tags"


def test_delete_many_by_keys_returns_removed_count() -> None:
    db = make_db(cursor_rows=[2])

    result = primitives.delete_many_by_keys(as_safe_db(db), "libraries", ["abc", "def"])

    assert result == 2
    call = db.aql.execute.call_args
    assert call is not None
    assert "REMOVE { _key: key } IN @@collection" in call.args[0]
    assert call.kwargs["bind_vars"] == {"@collection": "libraries", "keys": ["abc", "def"]}


def test_upsert_by_field_builds_expected_upsert_shape() -> None:
    db = make_db(cursor_rows=["libraries/abc"])

    result = primitives.upsert_by_field(
        as_safe_db(db),
        "libraries",
        "name",
        "Main",
        {"name": "Main", "watch_mode": "poll"},
    )

    assert result == "libraries/abc"
    call = db.aql.execute.call_args
    assert call is not None
    query = call.args[0]
    assert "UPSERT { name: @field_value }" in query
    assert "INSERT MERGE(@payload, { name: @field_value })" in query
    assert "RETURN NEW._id" in query
    assert call.kwargs["bind_vars"] == {
        "@collection": "libraries",
        "field_value": "Main",
        "payload": {"name": "Main", "watch_mode": "poll"},
    }


def test_insert_document_calls_collection_insert_and_returns_id() -> None:
    db = make_db(insert_result={"_id": "libraries/abc"})

    result = primitives.insert_document(as_safe_db(db), "libraries", {"name": "Main"})

    assert result == "libraries/abc"
    db.collection.assert_called_once_with("libraries")
    db._collection.insert.assert_called_once_with({"name": "Main"})


def test_update_document_by_key_uses_update_shape() -> None:
    db = make_db()

    primitives.update_document_by_key(as_safe_db(db), "libraries", "abc", {"watch_mode": "poll"})

    call = db.aql.execute.call_args
    assert call is not None
    assert "UPDATE { _key: @key }" in call.args[0]
    assert "WITH @fields" in call.args[0]
    assert call.kwargs["bind_vars"] == {
        "@collection": "libraries",
        "key": "abc",
        "fields": {"watch_mode": "poll"},
    }


def test_get_filtered_docs_no_sort_when_sort_field_is_none() -> None:
    db = make_db(cursor_rows=[{"name": "alpha"}])

    result = primitives.get_filtered_docs(
        as_safe_db(db),
        "libraries",
        filters={"name": "alpha"},
        sort_field=None,
        limit=10,
        allowed_fields={"name"},
    )

    assert result == [{"name": "alpha"}]
    call = db.aql.execute.call_args
    assert call is not None
    query = call.args[0]
    assert "SORT" not in query


def test_delete_many_by_field_rejects_disallowed_field() -> None:
    db = make_db()

    with pytest.raises(ValueError):
        primitives.delete_many_by_field(
            as_safe_db(db),
            "libraries",
            "forbidden",
            "value",
            allowed_fields={"name"},
        )

    db.aql.execute.assert_not_called()


def test_delete_many_by_field_rejects_invalid_field_name_before_query_execution() -> None:
    db = make_db()

    with pytest.raises(ValueError):
        primitives.delete_many_by_field(
            as_safe_db(db),
            "libraries",
            "bad-field",
            "value",
            allowed_fields={"bad-field"},
        )

    db.aql.execute.assert_not_called()


def test_delete_many_by_field_returns_zero_when_cursor_is_empty() -> None:
    db = make_db(cursor_rows=[])

    result = primitives.delete_many_by_field(
        as_safe_db(db),
        "libraries",
        "name",
        "Main",
        allowed_fields={"name"},
    )

    assert result == 0
    assert isinstance(result, int)


@pytest.mark.parametrize(
    "helper_name",
    ["upsert_many_by_field", "list_field_values"],
)
def test_removed_helpers_are_not_publicly_importable(helper_name: str) -> None:
    namespace: dict[str, Any] = {}

    with pytest.raises(ImportError):
        exec(f"from nomarr.persistence.aql.primitives import {helper_name}", namespace)

    assert not hasattr(primitives, helper_name)
