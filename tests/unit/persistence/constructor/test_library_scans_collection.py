"""Tests for constructor-backed access to the library_scans collection."""

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
def library_scans_namespace(mock_db: MagicMock):
    """Provide the constructor-backed library_scans namespace."""
    return SchemaConstructor(mock_db).build_collection_namespace(
        "library_scans",
        SCHEMA["library_scans"],
    )


class TestLibraryScansCollection:
    """Migration-coverage tests for the library_scans constructor namespace."""

    @pytest.mark.unit
    def test_library_key_lookup_returns_single_scan_doc(self, library_scans_namespace, mock_db) -> None:
        mock_db.aql.execute.return_value = iter(
            [{"library_key": "abc123", "status": "idle"}],
        )

        assert library_scans_namespace.library_key.get("abc123") == {
            "library_key": "abc123",
            "status": "idle",
        }

    @pytest.mark.unit
    def test_library_key_update_uses_constructor_field_update(self, library_scans_namespace, mock_db) -> None:
        library_scans_namespace.library_key.update("abc123", {"status": "scanning"})

        query = mock_db.aql.execute.call_args.args[0]
        bind_vars = mock_db.aql.execute.call_args.kwargs["bind_vars"]
        assert "UPDATE doc WITH @fields" in query
        assert bind_vars["field"] == "library_key"
        assert bind_vars["val"] == "abc123"
        assert bind_vars["fields"] == {"status": "scanning"}

    @pytest.mark.unit
    def test_status_lookup_returns_many_scan_docs(self, library_scans_namespace, mock_db) -> None:
        mock_db.aql.execute.return_value = iter(
            [
                {"library_key": "one", "status": "scanning"},
                {"library_key": "two", "status": "scanning"},
            ],
        )

        assert library_scans_namespace.status.get.many("scanning", limit=10) == [
            {"library_key": "one", "status": "scanning"},
            {"library_key": "two", "status": "scanning"},
        ]
