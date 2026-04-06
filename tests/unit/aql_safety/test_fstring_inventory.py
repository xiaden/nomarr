"""Tests for AQL f-string interpolation safety."""

from __future__ import annotations

import ast

import pytest

from .conftest import (
    _PERSISTENCE_DATABASE_ROOT,
    _find_fstring_interpolation_violations,
    _format_fstring_interpolation_violations,
    _FStringAqlVisitor,
)


class TestFStringAqlVisitorClassify:
    """Unit tests for the _FStringAqlVisitor._classify static method."""

    @pytest.mark.unit
    def test_collection_name_variable_classified(self) -> None:
        """collection_name variable is classified as the collection_name pattern."""
        node = ast.Name(id="collection_name", ctx=ast.Load())
        assert _FStringAqlVisitor._classify(node) == "collection_name"

    @pytest.mark.unit
    def test_nprobe_variable_classified_as_integer_param(self) -> None:
        """nprobe variable is classified as the integer_param pattern."""
        node = ast.Name(id="nprobe", ctx=ast.Load())
        assert _FStringAqlVisitor._classify(node) == "integer_param"

    @pytest.mark.unit
    def test_limit_clause_variable_classified(self) -> None:
        """limit_clause variable is classified as the limit_clause pattern."""
        node = ast.Name(id="limit_clause", ctx=ast.Load())
        assert _FStringAqlVisitor._classify(node) == "limit_clause"

    @pytest.mark.unit
    def test_unknown_variable_returns_none(self) -> None:
        """A variable with no matching taxonomy entry returns None."""
        node = ast.Name(id="user_input", ctx=ast.Load())
        assert _FStringAqlVisitor._classify(node) is None

    @pytest.mark.unit
    def test_ternary_expression_classified_as_conditional_fragment(self) -> None:
        """A ternary if-expression node is classified as conditional_fragment."""
        node = ast.parse("a if b else c", mode="eval").body
        assert _FStringAqlVisitor._classify(node) == "conditional_fragment"


@pytest.mark.unit
def test_fstring_aql_interpolations_are_safe() -> None:
    """Production AQL f-string interpolations should match reviewed safe patterns."""
    site_count, violations = _find_fstring_interpolation_violations(
        _PERSISTENCE_DATABASE_ROOT,
    )
    if violations:
        pytest.fail(_format_fstring_interpolation_violations(site_count, violations))
