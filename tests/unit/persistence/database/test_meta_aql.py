"""Tests for MetaOperations (meta_aql.py)."""

from __future__ import annotations

import pytest

from nomarr.persistence.database.meta_aql import MetaOperations


@pytest.fixture
def ops(mock_db):
    """Provide MetaOperations instance."""
    return MetaOperations(mock_db)


class TestHasVersion:
    """Tests for has_version()."""

    @pytest.mark.unit
    def test_returns_false_when_meta_collection_missing(self, ops, mock_db) -> None:
        """Returns False when the meta collection does not exist."""
        mock_db.has_collection.return_value = False

        assert ops.has_version() is False

    @pytest.mark.unit
    def test_returns_false_when_version_key_not_present(self, ops, mock_db) -> None:
        """Returns False when the version key is absent."""
        mock_db.has_collection.return_value = True
        mock_db.aql.execute.return_value = iter([])

        assert ops.has_version() is False

    @pytest.mark.unit
    def test_returns_true_when_version_key_exists(self, ops, mock_db) -> None:
        """Returns True when the version key is present."""
        mock_db.has_collection.return_value = True
        mock_db.aql.execute.return_value = iter(["1.0.0"])

        assert ops.has_version() is True
