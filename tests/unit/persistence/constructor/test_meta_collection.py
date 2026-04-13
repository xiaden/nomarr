"""Tests for constructor-backed access to the meta collection."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.constructor import SchemaConstructor
from nomarr.persistence.schema import SCHEMA


@pytest.fixture
def mock_db() -> MagicMock:
    """Provide a mock Arango database handle for constructor tests."""
    return MagicMock()


@pytest.fixture
def meta_namespace(mock_db: MagicMock):
    """Provide the constructor-backed meta namespace."""
    return SchemaConstructor(mock_db).build_collection_namespace("meta", SCHEMA["meta"])


class TestMetaVersionLookup:
    """Tests for `db.meta.key.get("version")` semantics."""

    @pytest.mark.unit
    def test_returns_none_when_version_key_not_present(self, meta_namespace, mock_db) -> None:
        """Missing version rows should return None."""
        mock_db.aql.execute.return_value = iter([])

        assert meta_namespace.key.get("version") is None

    @pytest.mark.unit
    def test_returns_document_when_version_key_exists(self, meta_namespace, mock_db) -> None:
        """Unique key lookup should return the stored meta document."""
        mock_db.aql.execute.return_value = iter([{"key": "version", "value": "1.0.0"}])

        assert meta_namespace.key.get("version") == {"key": "version", "value": "1.0.0"}

    @pytest.mark.unit
    def test_presence_check_uses_key_lookup_result(self, meta_namespace, mock_db) -> None:
        """Fresh-database checks now use `db.meta.key.get("version") is None`."""
        mock_db.aql.execute.return_value = iter([{"key": "version", "value": "1.0.0"}])

        assert meta_namespace.key.get("version") is not None
