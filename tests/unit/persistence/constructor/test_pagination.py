"""Tests for inject_pagination in constructor.pagination."""

from __future__ import annotations

import pytest

from nomarr.persistence.constructor.pagination import DEFAULT_LIMIT, inject_pagination


@pytest.mark.unit
@pytest.mark.mocked
class TestInjectPagination:
    """Tests for inject_pagination."""

    BASE_QUERY = "FOR doc IN col RETURN doc"

    def test_no_offset_default_limit(self) -> None:
        """limit=None and offset=0 appends LIMIT DEFAULT_LIMIT with no comma."""
        query, bind_vars = inject_pagination(self.BASE_QUERY, limit=None, offset=0)

        assert query.endswith("LIMIT @pagination_limit")
        assert bind_vars["pagination_limit"] == DEFAULT_LIMIT
        assert "pagination_offset" not in bind_vars

    def test_explicit_limit_no_offset(self) -> None:
        """Explicit limit with offset=0 appends LIMIT n with no comma."""
        query, bind_vars = inject_pagination(self.BASE_QUERY, limit=50, offset=0)

        assert query.endswith("LIMIT @pagination_limit")
        assert bind_vars["pagination_limit"] == 50
        assert "pagination_offset" not in bind_vars

    def test_offset_with_default_limit(self) -> None:
        """offset > 0 with limit=None appends LIMIT offset, DEFAULT_LIMIT."""
        query, bind_vars = inject_pagination(self.BASE_QUERY, limit=None, offset=10)

        assert "LIMIT @pagination_offset, @pagination_limit" in query
        assert bind_vars["pagination_offset"] == 10
        assert bind_vars["pagination_limit"] == DEFAULT_LIMIT

    def test_explicit_limit_and_offset(self) -> None:
        """Both explicit limit and offset appends LIMIT offset, limit."""
        query, bind_vars = inject_pagination(self.BASE_QUERY, limit=20, offset=5)

        assert "LIMIT @pagination_offset, @pagination_limit" in query
        assert bind_vars["pagination_offset"] == 5
        assert bind_vars["pagination_limit"] == 20

    def test_strips_trailing_whitespace_before_appending(self) -> None:
        """Trailing whitespace in the query is stripped before appending LIMIT."""
        query, _ = inject_pagination("FOR doc IN col RETURN doc   ", limit=None, offset=0)

        assert "doc   LIMIT" not in query
        assert "doc LIMIT" in query

    def test_zero_offset_does_not_produce_comma_form(self) -> None:
        """offset=0 always produces the single-argument LIMIT form."""
        query, bind_vars = inject_pagination(self.BASE_QUERY, limit=100, offset=0)

        assert "@pagination_limit" in query
        assert "pagination_offset" not in bind_vars
