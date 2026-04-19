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
        """limit=None and offset=0 inserts LIMIT before RETURN."""
        query, bind_vars = inject_pagination(self.BASE_QUERY, limit=None, offset=0)

        assert query == "FOR doc IN col LIMIT @pagination_limit RETURN doc"
        assert bind_vars["pagination_limit"] == DEFAULT_LIMIT
        assert "pagination_offset" not in bind_vars

    def test_explicit_limit_no_offset(self) -> None:
        """Explicit limit with offset=0 inserts LIMIT n before RETURN."""
        query, bind_vars = inject_pagination(self.BASE_QUERY, limit=50, offset=0)

        assert query == "FOR doc IN col LIMIT @pagination_limit RETURN doc"
        assert bind_vars["pagination_limit"] == 50
        assert "pagination_offset" not in bind_vars

    def test_offset_with_default_limit(self) -> None:
        """offset > 0 with limit=None inserts LIMIT offset, DEFAULT_LIMIT before RETURN."""
        query, bind_vars = inject_pagination(self.BASE_QUERY, limit=None, offset=10)

        assert query == "FOR doc IN col LIMIT @pagination_offset, @pagination_limit RETURN doc"
        assert bind_vars["pagination_offset"] == 10
        assert bind_vars["pagination_limit"] == DEFAULT_LIMIT

    def test_explicit_limit_and_offset(self) -> None:
        """Both explicit limit and offset inserts LIMIT offset, limit before RETURN."""
        query, bind_vars = inject_pagination(self.BASE_QUERY, limit=20, offset=5)

        assert query == "FOR doc IN col LIMIT @pagination_offset, @pagination_limit RETURN doc"
        assert bind_vars["pagination_offset"] == 5
        assert bind_vars["pagination_limit"] == 20

    def test_strips_trailing_whitespace(self) -> None:
        """Trailing whitespace in the query is stripped."""
        query, _ = inject_pagination("FOR doc IN col RETURN doc   ", limit=None, offset=0)

        assert query == "FOR doc IN col LIMIT @pagination_limit RETURN doc"

    def test_zero_offset_does_not_produce_comma_form(self) -> None:
        """offset=0 always produces the single-argument LIMIT form."""
        query, bind_vars = inject_pagination(self.BASE_QUERY, limit=100, offset=0)

        assert "LIMIT @pagination_limit RETURN" in query
        assert "pagination_offset" not in bind_vars
