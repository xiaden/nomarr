"""Tests for graph traversal verb functions in constructor.verbs."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from nomarr.persistence.constructor.verbs import (
    aggregate_field,
    ann_search,
    collect_field,
    count_by_filter,
    delete_by_filter,
    delete_by_ids,
    get_many_by_filter,
    insert,
    traversal_by_filter,
    traversal_by_filter_with_target_filter,
    traversal_by_id,
    traversal_by_ids,
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
            raise_on_document_error=True,
        )

    def test_insert_empty_list_returns_empty_list(self) -> None:
        """insert() returns an empty list for an empty batch while still calling insert_many."""
        db = MagicMock()
        db.collection.return_value.insert_many.return_value = []

        result = insert(db, "items", [])

        assert result == []
        db.collection.assert_called_once_with("items")
        db.collection.return_value.insert_many.assert_called_once_with(
            [], return_new=True, raise_on_document_error=True
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestUpsertByField:
    """Tests for upsert_by_field."""

    def test_single_field_returns_id_list_for_docs_list(self) -> None:
        """Single-field upsert executes one AQL query for all docs and returns a list of ``_id`` values."""
        db = MagicMock()
        db.aql.execute.return_value = iter(["items/1", "items/2"])

        result = upsert_by_field(
            db,
            "items",
            "slug",
            [{"slug": "foo"}, {"slug": "bar"}],
        )

        assert result == ["items/1", "items/2"]
        assert db.aql.execute.call_count == 1
        call = db.aql.execute.call_args_list[0]
        assert "UPSERT" in call.args[0]
        assert "`slug`: doc.`slug`" in call.args[0]
        assert call.kwargs["bind_vars"] == {
            "@col": "items",
            "docs": [{"slug": "foo"}, {"slug": "bar"}],
        }

    def test_compound_key_uses_keep_and_single_query(self) -> None:
        """Compound-key upsert uses object literal search expression and issues a single AQL query for all docs."""
        db = MagicMock()
        db.aql.execute.return_value = iter(["tags/1", "tags/2"])
        docs = [
            {"name": "genre", "value": "rock", "weight": 1.0},
            {"name": "mood", "value": "energetic", "weight": 0.8},
        ]

        result = upsert_by_field(db, "tags", ["name", "value"], docs)

        assert result == ["tags/1", "tags/2"]
        assert db.aql.execute.call_count == 1
        call = db.aql.execute.call_args_list[0]
        assert "`name`: doc.`name`" in call.args[0]
        assert "`value`: doc.`value`" in call.args[0]
        assert call.kwargs["bind_vars"] == {
            "@col": "tags",
            "docs": docs,
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
            "FOR id IN @ids REMOVE {_key: PARSE_IDENTIFIER(id).key} IN @@col",
            bind_vars={"@col": "items", "ids": ["items/1", "items/2"]},
            ttl=6000,
        )

    def test_delete_by_ids_with_empty_list_passes_empty_ids(self) -> None:
        """delete_by_ids() forwards an empty ids list unchanged in the AQL bind vars."""
        db = MagicMock()

        delete_by_ids(db, "items", [])

        db.aql.execute.assert_called_once_with(
            "FOR id IN @ids REMOVE {_key: PARSE_IDENTIFIER(id).key} IN @@col",
            bind_vars={"@col": "items", "ids": []},
            ttl=6000,
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
            {"name": "genre"},
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
            "f0": "name",
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

        result = count_by_filter(db, "tags", {"name": "genre", "value": "rock"})

        assert result == 3
        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        bind_vars = call_args.kwargs["bind_vars"]
        assert "FILTER doc[@f0] == @v0 AND doc[@f1] == @v1" in aql
        assert "COLLECT WITH COUNT INTO c" in aql
        assert bind_vars == {
            "@col": "tags",
            "f0": "name",
            "v0": "genre",
            "f1": "value",
            "v1": "rock",
        }

    def test_delete_by_filter_returns_deleted_count(self) -> None:
        """delete_by_filter returns the number of removed rows."""
        db = _mock_db([1, 1])

        result = delete_by_filter(db, "tags", {"name": "genre"})

        assert result == 2
        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        bind_vars = call_args.kwargs["bind_vars"]
        assert "FILTER doc[@f0] == @v0" in aql
        assert "REMOVE doc IN @@col" in aql
        assert "RETURN 1" in aql
        assert bind_vars == {
            "@col": "tags",
            "f0": "name",
            "v0": "genre",
        }

    def test_update_by_filter_updates_matching_documents(self) -> None:
        """update_by_filter uses the equality filter and forwards update fields."""
        db = MagicMock()

        update_by_filter(db, "tags", {"name": "genre"}, {"value": "jazz"})

        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        bind_vars = call_args.kwargs["bind_vars"]
        assert "FILTER doc[@f0] == @v0" in aql
        assert "UPDATE doc WITH @fields IN @@col" in aql
        assert bind_vars == {
            "@col": "tags",
            "fields": {"value": "jazz"},
            "f0": "name",
            "v0": "genre",
        }


@pytest.mark.unit
@pytest.mark.mocked
class TestAnnSearch:
    """Tests for ANN vector search verb generation."""

    def test_ann_search_iterates_bound_collection_and_uses_doc_vector_score(self) -> None:
        """ann_search() must score docs from the bound collection, not use the collection as an operand."""
        db = _mock_db([{"file_id": "library_files/1", "score": 0.99}])

        result = ann_search(
            db,
            "vectors_track_cold__effnet__216882179",
            [0.1, 0.2, 0.3],
            limit=10,
            nprobe=4,
        )

        assert result == [{"file_id": "library_files/1", "score": 0.99}]
        call_args = db.aql.execute.call_args
        aql = call_args.args[0]
        bind_vars = call_args.kwargs["bind_vars"]
        assert "FOR doc IN @@col" in aql
        assert "LET score = APPROX_NEAR_COSINE(doc.vector_n, @query_vector, {nProbe: @nprobe})" in aql
        assert "SORT score DESC" in aql
        assert "FOR doc IN APPROX_NEAR_COSINE(@@col, @query_vector, @nprobe)" not in aql
        assert bind_vars == {
            "@col": "vectors_track_cold__effnet__216882179",
            "query_vector": [0.1, 0.2, 0.3],
            "nprobe": 4,
            "limit": 10,
        }


@pytest.mark.unit
@pytest.mark.mocked
class TestFilteredCollectAndAggregate:
    """Tests for collect_field and aggregate_field filter forwarding."""

    def test_collect_field_with_filter_places_filter_before_collect(self) -> None:
        """collect_field inserts FILTER before the COLLECT clause when provided."""
        db = _mock_db(["rock"])

        result = collect_field(db, "tags", "value", filter={"name": "genre"}, limit=10)

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
            "f0": "name",
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
        }

    def test_aggregate_field_with_filter_places_filter_before_collect(self) -> None:
        """aggregate_field inserts FILTER before COLLECT when provided."""
        db = _mock_db([{"value": "rock", "count": 2}])

        result = aggregate_field(db, "tags", "value", filter={"name": "genre"}, limit=10)

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
            "f0": "name",
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
class TestTraversalByIds:
    """Tests for traversal_by_ids."""

    def test_outbound_builds_outbound_aql(self) -> None:
        """Returns documents; AQL contains OUTBOUND with start_ids bind var."""
        db = _mock_db([{"_id": "target/1"}])

        result = traversal_by_ids(db, "src_col", ["src_col/1", "src_col/2"], "my_edge", "OUTBOUND")

        assert result == [{"_id": "target/1"}]
        call_args = db.aql.execute.call_args
        assert "OUTBOUND" in call_args[0][0]
        assert call_args[1]["bind_vars"]["start_ids"] == ["src_col/1", "src_col/2"]
        assert call_args[1]["bind_vars"]["@edge"] == "my_edge"

    def test_inbound_builds_inbound_aql(self) -> None:
        """INBOUND direction produces AQL with INBOUND keyword."""
        db = _mock_db()

        traversal_by_ids(db, "src_col", ["src_col/1"], "my_edge", "INBOUND")

        assert "INBOUND" in db.aql.execute.call_args[0][0]

    def test_invalid_direction_raises_value_error(self) -> None:
        """Unsupported direction raises ValueError with the direction name."""
        db = _mock_db()

        with pytest.raises(ValueError, match="SIDEWAYS"):
            traversal_by_ids(db, "src_col", ["src_col/1"], "my_edge", "SIDEWAYS")

    def test_empty_result_returns_empty_list(self) -> None:
        """No documents returned from db produces empty list."""
        db = _mock_db([])

        result = traversal_by_ids(db, "src_col", ["src_col/1"], "my_edge", "OUTBOUND")

        assert result == []

    def test_target_filter_adds_filter_clause_and_bind_vars(self) -> None:
        """target_filter encodes field/value as tgt_field_N/tgt_val_N bind vars."""
        db = _mock_db()

        traversal_by_ids(db, "col", ["col/1"], "edge", "OUTBOUND", target_filter={"genre": "rock"})

        bind_vars = db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["tgt_val_0"] == "rock"
        assert bind_vars["tgt_field_0"] == "genre"
        assert "FILTER" in db.aql.execute.call_args[0][0]

    def test_target_like_starts_with_adds_starts_with_filter(self) -> None:
        """target_like_starts_with encodes sw_field/sw_prefix and adds STARTS_WITH to AQL."""
        db = _mock_db()

        traversal_by_ids(
            db,
            "col",
            ["col/1"],
            "edge",
            "OUTBOUND",
            target_like_starts_with=("name", "Ar"),
        )

        bind_vars = db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["sw_field"] == "name"
        assert bind_vars["sw_prefix"] == "Ar"
        assert "STARTS_WITH" in db.aql.execute.call_args[0][0]

    def test_combined_target_filter_and_target_like_starts_with_generates_and_clause(self) -> None:
        """Both target_filter and target_like_starts_with produce FILTER joined with AND."""
        db = _mock_db()

        traversal_by_ids(
            db,
            "col",
            ["col/1"],
            "edge",
            "OUTBOUND",
            target_filter={"genre": "rock"},
            target_like_starts_with=("name", "Ar"),
        )

        aql = db.aql.execute.call_args[0][0]
        bind_vars = db.aql.execute.call_args[1]["bind_vars"]
        assert "tgt_val_0" in bind_vars
        assert "sw_prefix" in bind_vars
        assert "AND" in aql
        assert "FILTER" in aql

    def test_multiple_target_filter_entries_produce_multiple_bind_vars(self) -> None:
        """Multiple target_filter entries produce indexed tgt_field_N/tgt_val_N bind vars."""
        db = _mock_db()

        traversal_by_ids(
            db,
            "col",
            ["col/1"],
            "edge",
            "OUTBOUND",
            target_filter={"genre": "rock", "year": 2020},
        )

        bind_vars = db.aql.execute.call_args[1]["bind_vars"]
        assert "tgt_field_0" in bind_vars
        assert "tgt_val_0" in bind_vars
        assert "tgt_field_1" in bind_vars
        assert "tgt_val_1" in bind_vars


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
