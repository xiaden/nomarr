"""Tests for graph traversal verb functions in constructor.verbs."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from nomarr.persistence.constructor.verbs import (
    aggregate_field,
    collect_field,
    count_by_filter,
    delete_by_filter,
    delete_by_ids,
    get_many_by_filter,
    insert,
    traversal_by_filter,
    traversal_by_filter_with_target_filter,
    traversal_by_id,
    update_by_filter,
    upsert_by_field,
)


def _mock_db(docs: list[Any] | None = None) -> MagicMock:
    """Build a mock db where aql.execute returns the given documents."""
    db = MagicMock()
    db.aql.execute.return_value = iter(docs or [])
    return db


@pytest.mark.unit
@pytest.mark.mocked
class TestInsert:
    """Tests for insert."""

    def test_insert_returns_id_list_for_docs_list(self) -> None:
        """insert() accepts a docs list and returns a list of inserted ``_id`` values."""
        db = MagicMock()
        db.collection.return_value.insert_many.return_value = [
            {"new": {"_id": "items/1"}},
            {"new": {"_id": "items/2"}},
        ]

        result = insert(db, "items", [{"title": "foo"}, {"title": "bar"}])

        assert result == ["items/1", "items/2"]
        db.collection.assert_called_once_with("items")
        db.collection.return_value.insert_many.assert_called_once_with(
            [{"title": "foo"}, {"title": "bar"}],
            return_new=True,
        )

    def test_insert_empty_list_returns_empty_list(self) -> None:
        """insert() returns an empty list for an empty batch while still calling insert_many."""
        db = MagicMock()
        db.collection.return_value.insert_many.return_value = []

        result = insert(db, "items", [])

        assert result == []
        db.collection.assert_called_once_with("items")
        db.collection.return_value.insert_many.assert_called_once_with([], return_new=True)


@pytest.mark.unit
@pytest.mark.mocked
class TestUpsertByField:
    """Tests for upsert_by_field."""

    def test_single_field_returns_id_list_for_docs_list(self) -> None:
        """Single-field upsert iterates docs and returns a list of ``_id`` values."""
        db = MagicMock()
        db.aql.execute.side_effect = [iter(["items/1"]), iter(["items/2"])]

        result = upsert_by_field(
            db,
            "items",
            "slug",
            [{"slug": "foo"}, {"slug": "bar"}],
        )

        assert result == ["items/1", "items/2"]
        first_call = db.aql.execute.call_args_list[0]
        assert "UPSERT" in first_call.args[0]
        assert first_call.kwargs["bind_vars"] == {
            "@col": "items",
            "field": "slug",
            "key_val": "foo",
            "doc": {"slug": "foo"},
        }

    def test_compound_key_builds_indexed_bind_vars(self) -> None:
        """Compound-key upsert emits indexed field bind vars and compound UPSERT AQL."""
        db = MagicMock()
        db.aql.execute.side_effect = [iter(["tags/1"]), iter(["tags/2"])]
        docs = [
            {"rel": "genre", "value": "rock", "weight": 1.0},
            {"rel": "mood", "value": "energetic", "weight": 0.8},
        ]

        result = upsert_by_field(db, "tags", ["rel", "value"], docs)

        assert result == ["tags/1", "tags/2"]
        first_call = db.aql.execute.call_args_list[0]
        assert "FOR doc IN @docs UPSERT { [@f0]: doc[@f0], [@f1]: doc[@f1] }" in first_call.args[0]
        assert first_call.kwargs["bind_vars"] == {
            "@col": "tags",
            "docs": [docs[0]],
            "f0": "rel",
            "f1": "value",
        }

    def test_empty_docs_list_returns_empty_list_without_db_call(self) -> None:
        """upsert_by_field() returns an empty list without executing AQL for an empty docs list."""
        db = MagicMock()

        result = upsert_by_field(db, "items", "slug", [])

        assert result == []
        db.aql.execute.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
class TestDeleteByIds:
    """Tests for delete_by_ids."""

    def test_delete_by_ids_uses_list_bind_var(self) -> None:
        """delete_by_ids() accepts a list of ids and forwards that list unchanged."""
        db = MagicMock()

        delete_by_ids(db, "items", ["items/1", "items/2"])

        db.aql.execute.assert_called_once_with(
            "FOR id IN @ids REMOVE {_id: id} IN @@col",
            bind_vars={"@col": "items", "ids": ["items/1", "items/2"]},
        )

    def test_delete_by_ids_with_empty_list_passes_empty_ids(self) -> None:
        """delete_by_ids() forwards an empty ids list unchanged in the AQL bind vars."""
        db = MagicMock()

        delete_by_ids(db, "items", [])

        db.aql.execute.assert_called_once_with(
            "FOR id IN @ids REMOVE {_id: id} IN @@col",
            bind_vars={"@col": "items", "ids": []},
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestFilterVerbs:
    """Tests for the multi-field equality filter verbs."""

    def test_get_many_by_filter_includes_filter_and_pagination(self) -> None:
        """get_many_by_filter injects the FILTER fragment and pagination bind vars."""
        db = _mock_db([{"_id": "tags/1"}])

        result = get_many_by_filter(
            db,
            "tags",
            {"rel": "genre"},
            limit=10,
            offset=5,
        )

        assert result == [{"_id": "tags/1"}]
        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        bind_vars = call_args.kwargs["bind_vars"]
        assert "FILTER doc[@f0] == @v0" in aql
        assert "LIMIT @pagination_offset, @pagination_limit" in aql
        assert bind_vars == {
            "@col": "tags",
            "f0": "rel",
            "v0": "genre",
            "pagination_offset": 5,
            "pagination_limit": 10,
        }

    def test_get_many_by_filter_empty_filter_omits_filter_clause(self) -> None:
        """An empty filter dict produces no FILTER clause in the query."""
        db = _mock_db([{"_id": "tags/1"}])

        result = get_many_by_filter(db, "tags", {}, limit=10)

        assert result == [{"_id": "tags/1"}]
        call_args = db.aql.execute.call_args
        assert "FILTER" not in call_args.args[0]
        assert call_args.kwargs["bind_vars"] == {
            "@col": "tags",
            "pagination_limit": 10,
        }

    def test_count_by_filter_includes_collect_count(self) -> None:
        """count_by_filter uses the equality filter and COLLECT WITH COUNT."""
        db = _mock_db([3])

        result = count_by_filter(db, "tags", {"rel": "genre", "value": "rock"})

        assert result == 3
        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        bind_vars = call_args.kwargs["bind_vars"]
        assert "FILTER doc[@f0] == @v0 AND doc[@f1] == @v1" in aql
        assert "COLLECT WITH COUNT INTO c" in aql
        assert bind_vars == {
            "@col": "tags",
            "f0": "rel",
            "v0": "genre",
            "f1": "value",
            "v1": "rock",
        }

    def test_delete_by_filter_returns_deleted_count(self) -> None:
        """delete_by_filter returns the number of removed rows."""
        db = _mock_db([1, 1])

        result = delete_by_filter(db, "tags", {"rel": "genre"})

        assert result == 2
        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        bind_vars = call_args.kwargs["bind_vars"]
        assert "FILTER doc[@f0] == @v0" in aql
        assert "REMOVE doc IN @@col" in aql
        assert "RETURN 1" in aql
        assert bind_vars == {
            "@col": "tags",
            "f0": "rel",
            "v0": "genre",
        }

    def test_update_by_filter_updates_matching_documents(self) -> None:
        """update_by_filter uses the equality filter and forwards update fields."""
        db = MagicMock()

        update_by_filter(db, "tags", {"rel": "genre"}, {"value": "jazz"})

        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        bind_vars = call_args.kwargs["bind_vars"]
        assert "FILTER doc[@f0] == @v0" in aql
        assert "UPDATE doc WITH @fields IN @@col" in aql
        assert bind_vars == {
            "@col": "tags",
            "fields": {"value": "jazz"},
            "f0": "rel",
            "v0": "genre",
        }


@pytest.mark.unit
@pytest.mark.mocked
class TestFilteredCollectAndAggregate:
    """Tests for collect_field and aggregate_field filter forwarding."""

    def test_collect_field_with_filter_places_filter_before_collect(self) -> None:
        """collect_field inserts FILTER before the COLLECT clause when provided."""
        db = _mock_db(["rock"])

        result = collect_field(db, "tags", "value", filter={"rel": "genre"}, limit=10)

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

    def test_collect_field_without_filter_preserves_existing_behavior(self) -> None:
        """collect_field omits FILTER when filter is None."""
        db = _mock_db(["rock"])

        result = collect_field(db, "tags", "value")

        assert result == ["rock"]
        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        assert "FILTER" not in aql
        assert "COLLECT val = doc[@field]" in aql
        assert call_args.kwargs["bind_vars"] == {
            "@col": "tags",
            "field": "value",
            "pagination_limit": 1000,
        }

    def test_aggregate_field_with_filter_places_filter_before_collect(self) -> None:
        """aggregate_field inserts FILTER before COLLECT when provided."""
        db = _mock_db([{"value": "rock", "count": 2}])

        result = aggregate_field(db, "tags", "value", filter={"rel": "genre"}, limit=10)

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

    def test_aggregate_field_without_filter_preserves_existing_behavior(self) -> None:
        """aggregate_field omits FILTER when filter is not provided."""
        db = _mock_db([{"value": "rock", "count": 2}])

        result = aggregate_field(db, "tags", "value")

        assert result == [{"value": "rock", "count": 2}]
        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        assert "FILTER" not in aql
        assert "COLLECT val = doc[@field] WITH COUNT INTO c" in aql
        assert call_args.kwargs["bind_vars"] == {
            "@col": "tags",
            "field": "value",
            "pagination_limit": 1000,
        }


@pytest.mark.unit
@pytest.mark.mocked
class TestTraversalById:
    """Tests for traversal_by_id."""

    def test_outbound_builds_outbound_aql(self) -> None:
        """Returns documents; AQL contains OUTBOUND with correct bind vars."""
        db = _mock_db([{"_id": "target/1"}])

        result = traversal_by_id(db, "src_col", "src_col/1", "my_edge", "OUTBOUND")

        assert result == [{"_id": "target/1"}]
        call_args = db.aql.execute.call_args
        assert "OUTBOUND" in call_args[0][0]
        assert call_args[1]["bind_vars"]["start_id"] == "src_col/1"
        assert call_args[1]["bind_vars"]["@edge"] == "my_edge"

    def test_inbound_builds_inbound_aql(self) -> None:
        """INBOUND direction produces AQL with INBOUND keyword."""
        db = _mock_db()

        traversal_by_id(db, "src_col", "src_col/1", "my_edge", "INBOUND")

        assert "INBOUND" in db.aql.execute.call_args[0][0]

    def test_invalid_direction_raises_value_error(self) -> None:
        """Unsupported direction raises ValueError with the direction name."""
        db = _mock_db()

        with pytest.raises(ValueError, match="SIDEWAYS"):
            traversal_by_id(db, "src_col", "src_col/1", "my_edge", "SIDEWAYS")

    def test_empty_result_returns_empty_list(self) -> None:
        """No documents returned from db produces empty list."""
        db = _mock_db([])

        result = traversal_by_id(db, "src_col", "src_col/1", "my_edge", "OUTBOUND")

        assert result == []


@pytest.mark.unit
@pytest.mark.mocked
class TestTraversalByFilter:
    """Tests for traversal_by_filter."""

    def test_outbound_returns_documents_and_uses_outbound_aql(self) -> None:
        """Returns traversed documents; AQL uses OUTBOUND."""
        db = _mock_db([{"_id": "target/2"}])

        result = traversal_by_filter(db, "src_col", {"status": "active"}, "my_edge", "OUTBOUND")

        assert result == [{"_id": "target/2"}]
        call_args = db.aql.execute.call_args
        assert "OUTBOUND" in call_args[0][0]
        assert call_args[1]["bind_vars"]["@col"] == "src_col"
        assert call_args[1]["bind_vars"]["@edge"] == "my_edge"

    def test_inbound_uses_inbound_keyword(self) -> None:
        """INBOUND direction produces AQL with INBOUND keyword."""
        db = _mock_db()

        traversal_by_filter(db, "src_col", {"status": "active"}, "my_edge", "INBOUND")

        assert "INBOUND" in db.aql.execute.call_args[0][0]

    def test_source_filter_values_encoded_in_bind_vars(self) -> None:
        """Each source filter key/value is stored in indexed bind vars."""
        db = _mock_db()

        traversal_by_filter(db, "col", {"lib_id": "lib/1", "active": True}, "edge", "OUTBOUND")

        bind_vars = db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["src_val_0"] == "lib/1"
        assert bind_vars["src_val_1"] is True

    def test_invalid_direction_raises_value_error(self) -> None:
        """Unsupported direction raises ValueError."""
        db = _mock_db()

        with pytest.raises(ValueError, match="LATERAL"):
            traversal_by_filter(db, "col", {"f": "v"}, "edge", "LATERAL")


@pytest.mark.unit
@pytest.mark.mocked
class TestTraversalByFilterWithTargetFilter:
    """Tests for traversal_by_filter_with_target_filter."""

    def test_outbound_includes_source_and_target_filter_clauses(self) -> None:
        """Returns documents; AQL has OUTBOUND and two FILTER blocks."""
        db = _mock_db([{"_id": "target/3"}])

        result = traversal_by_filter_with_target_filter(
            db, "src_col", {"status": "active"}, "edge", "OUTBOUND", {"genre": "rock"}
        )

        assert result == [{"_id": "target/3"}]
        call_args = db.aql.execute.call_args
        aql = call_args[0][0]
        assert "OUTBOUND" in aql
        assert aql.count("FILTER") >= 2
        assert call_args[1]["bind_vars"]["tgt_val_0"] == "rock"

    def test_inbound_uses_inbound_keyword(self) -> None:
        """INBOUND direction produces AQL with INBOUND keyword."""
        db = _mock_db()

        traversal_by_filter_with_target_filter(db, "src_col", {"s": "v"}, "edge", "INBOUND", {"t": "w"})

        assert "INBOUND" in db.aql.execute.call_args[0][0]

    def test_target_filter_values_in_bind_vars(self) -> None:
        """Target filter fields are encoded with tgt_ prefix in bind vars."""
        db = _mock_db()

        traversal_by_filter_with_target_filter(db, "col", {"src_field": "x"}, "edge", "OUTBOUND", {"tgt_field": "y"})

        bind_vars = db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["tgt_val_0"] == "y"
        assert bind_vars["tgt_field_0"] == "tgt_field"

    def test_invalid_direction_raises_value_error(self) -> None:
        """Unsupported direction raises ValueError."""
        db = _mock_db()

        with pytest.raises(ValueError, match="DIAGONAL"):
            traversal_by_filter_with_target_filter(db, "col", {"f": "v"}, "edge", "DIAGONAL", {"g": "w"})


@pytest.mark.unit
@pytest.mark.mocked
class TestTruncate:
    """Tests for the truncate verb."""

    def test_truncate_calls_collection_truncate(self) -> None:
        """truncate() delegates to python-arango collection.truncate()."""
        from nomarr.persistence.constructor.verbs import truncate

        db = MagicMock()
        truncate(db, "my_collection")
        db.collection.assert_called_once_with("my_collection")
        db.collection.return_value.truncate.assert_called_once()
