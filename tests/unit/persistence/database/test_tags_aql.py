"""Tests for nomarr.persistence.database.tags_aql module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.tags_aql import TagsAqlOperations


class TestAggregateTagField:
    """Tests for TagsAqlOperations.aggregate_tag_field."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_allows_underscore_id_field(self) -> None:
        mock_safe_db = MagicMock()
        mock_safe_db.aql.execute.return_value = [{"value": "tags/1", "count": 1}]
        ops = TagsAqlOperations(mock_safe_db)

        result = ops.aggregate_tag_field("_id", limit=5, offset=2)

        assert result == [{"value": "tags/1", "count": 1}]
        mock_safe_db.aql.execute.assert_called_once()
        query = mock_safe_db.aql.execute.call_args.kwargs["bind_vars"]
        assert query == {"@collection": "tags", "offset": 2, "limit": 5}
