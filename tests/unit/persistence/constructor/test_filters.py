"""Tests for filter builder functions in constructor.filters."""

from __future__ import annotations

import pytest

from nomarr.helpers.filter_types import Op
from nomarr.persistence.constructor.filters import (
    build_comparison_filter,
    build_equality_filter,
    build_in_filter,
    build_like_filter,
)


@pytest.mark.unit
@pytest.mark.mocked
class TestBuildInFilter:
    """Tests for build_in_filter."""

    def test_produces_in_filter_fragment(self) -> None:
        """Returns AQL fragment using IN operator with correct bind vars."""
        aql, bind_vars = build_in_filter("status", ["active", "pending"])

        assert "IN @vals" in aql
        assert bind_vars["field"] == "status"
        assert bind_vars["vals"] == ["active", "pending"]

    def test_uses_doc_field_bind_var(self) -> None:
        """Field is accessed via bind var, not interpolated directly."""
        aql, _ = build_in_filter("status", ["active"])

        assert "doc[@field]" in aql

    def test_custom_bind_prefix_replaces_default(self) -> None:
        """custom bind_prefix overrides the default 'vals' key."""
        aql, bind_vars = build_in_filter("ids", [1, 2, 3], bind_prefix="id_list")

        assert "IN @id_list" in aql
        assert bind_vars["id_list"] == [1, 2, 3]
        assert "vals" not in bind_vars


@pytest.mark.unit
@pytest.mark.mocked
class TestBuildComparisonFilter:
    """Tests for build_comparison_filter."""

    def test_single_lt_produces_one_filter_clause(self) -> None:
        """Op.LT with one entry produces a single FILTER clause with <."""
        aql, bind_vars = build_comparison_filter("count", {Op.LT: 100})

        assert "FILTER" in aql
        assert "<" in aql
        assert bind_vars["cmp_val_0"] == 100

    def test_field_bind_var_present(self) -> None:
        """The field name is always included as bind var 'field'."""
        _, bind_vars = build_comparison_filter("score", {Op.GTE: 5})

        assert bind_vars["field"] == "score"

    def test_multiple_ops_produce_multiple_filter_clauses(self) -> None:
        """Two ops produce two separate FILTER clauses."""
        aql, bind_vars = build_comparison_filter("year", {Op.GTE: 2000, Op.LTE: 2020})

        assert aql.count("FILTER") == 2
        assert bind_vars["cmp_val_0"] == 2000
        assert bind_vars["cmp_val_1"] == 2020

    def test_eq_op_uses_double_equals(self) -> None:
        """Op.EQ maps to == in the AQL fragment."""
        aql, _ = build_comparison_filter("active", {Op.EQ: True})

        assert "==" in aql

    def test_neq_op_uses_not_equals(self) -> None:
        """Op.NEQ maps to != in the AQL fragment."""
        aql, _ = build_comparison_filter("active", {Op.NEQ: False})

        assert "!=" in aql

    def test_gt_op_uses_greater_than(self) -> None:
        """Op.GT maps to > in the AQL fragment."""
        aql, _ = build_comparison_filter("age", {Op.GT: 18})

        assert ">" in aql
        assert "<" not in aql


@pytest.mark.unit
@pytest.mark.mocked
class TestBuildEqualityFilter:
    """Tests for build_equality_filter."""

    def test_single_field_dict_produces_one_filter_clause(self) -> None:
        """A one-field equality filter produces a single FILTER expression."""
        aql, bind_vars = build_equality_filter({"name": "genre"})

        assert aql == "FILTER doc[@f0] == @v0"
        assert bind_vars == {"f0": "name", "v0": "genre"}

    def test_multi_field_dict_produces_and_joined_filter_clause(self) -> None:
        """Multiple fields produce one FILTER clause joined with AND."""
        aql, bind_vars = build_equality_filter({"name": "genre", "value": "rock"})

        assert aql == "FILTER doc[@f0] == @v0 AND doc[@f1] == @v1"
        assert bind_vars == {
            "f0": "name",
            "v0": "genre",
            "f1": "value",
            "v1": "rock",
        }

    def test_empty_dict_returns_empty_fragment_and_bind_vars(self) -> None:
        """An empty equality filter is a no-op with no FILTER clause."""
        aql, bind_vars = build_equality_filter({})

        assert aql == ""
        assert bind_vars == {}


@pytest.mark.unit
@pytest.mark.mocked
class TestBuildLikeFilter:
    """Tests for build_like_filter."""

    def test_produces_like_aql_fragment(self) -> None:
        """Produces LIKE AQL fragment with field and pattern bind vars."""
        aql, bind_vars = build_like_filter("name", "%rock%")

        assert "LIKE" in aql
        assert bind_vars["field"] == "name"
        assert bind_vars["like_pattern"] == "%rock%"

    def test_uses_doc_field_bind_var(self) -> None:
        """Field is accessed via bind var in the LIKE expression."""
        aql, _ = build_like_filter("title", "test%")

        assert "doc[@field]" in aql

    def test_pattern_preserved_exactly(self) -> None:
        """The pattern is stored verbatim in the bind vars."""
        _, bind_vars = build_like_filter("path", "%/music/%")

        assert bind_vars["like_pattern"] == "%/music/%"
