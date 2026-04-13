"""Tests for constructor-backed access to the library_folders collection."""

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
def library_folders_namespace(mock_db: MagicMock):
    """Provide the constructor-backed library_folders namespace."""
    return SchemaConstructor(mock_db).build_collection_namespace(
        "library_folders",
        SCHEMA["library_folders"],
    )


class TestLibraryFoldersCollection:
    """Migration-coverage tests for the library_folders constructor namespace."""

    @pytest.mark.unit
    def test_collection_get_reads_folder_by_id(self, library_folders_namespace, mock_db) -> None:
        mock_db.collection.return_value.get.return_value = {"_id": "library_folders/abc", "path": "Rock"}

        assert library_folders_namespace.get("library_folders/abc") == {
            "_id": "library_folders/abc",
            "path": "Rock",
        }

    @pytest.mark.unit
    def test_insert_returns_folder_id(self, library_folders_namespace, mock_db) -> None:
        mock_db.collection.return_value.insert_many.return_value = [{"new": {"_id": "library_folders/abc"}}]

        result = library_folders_namespace.insert(
            [
                {"_key": "abc", "path": "Rock", "library_key": "lib1"},
            ]
        )

        assert result == ["library_folders/abc"]

    @pytest.mark.unit
    def test_library_key_collect_returns_distinct_library_keys(self, library_folders_namespace, mock_db) -> None:
        mock_db.aql.execute.return_value = iter(["lib1", "lib2"])

        assert library_folders_namespace.library_key.collect(limit=10) == ["lib1", "lib2"]
