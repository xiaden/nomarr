"""Tests for constructor-backed access to the library_pipeline_states collection."""

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
def library_pipeline_states_namespace(mock_db: MagicMock):
    """Provide the constructor-backed library_pipeline_states namespace."""
    return SchemaConstructor(mock_db).build_collection_namespace(
        "library_pipeline_states",
        SCHEMA["library_pipeline_states"],
    )


class TestLibraryPipelineStatesCollection:
    """Migration-coverage tests for the pipeline-state constructor namespace."""

    @pytest.mark.unit
    def test_library_key_lookup_returns_single_state_doc(self, library_pipeline_states_namespace, mock_db) -> None:
        """`library_key.get()` replaces the old get_state lookup root."""
        mock_db.aql.execute.return_value = iter(
            [{"library_key": "abc123", "pipeline_state": "library_pipeline_states/scanning"}],
        )

        assert library_pipeline_states_namespace.library_key.get("abc123") == {
            "library_key": "abc123",
            "pipeline_state": "library_pipeline_states/scanning",
        }

    @pytest.mark.unit
    def test_library_key_upsert_accepts_pipeline_payload(self, library_pipeline_states_namespace, mock_db) -> None:
        """`library_key.upsert()` replaces the old transition helper's persistence write."""
        mock_db.aql.execute.return_value = iter(["library_pipeline_states/1"])

        result = library_pipeline_states_namespace.library_key.upsert(
            [{"library_key": "abc123", "pipeline_state": "library_pipeline_states/idle"}],
            match_field="library_key",
        )

        assert result == ["library_pipeline_states/1"]

    @pytest.mark.unit
    def test_pipeline_state_lookup_returns_all_matching_library_docs(
        self, library_pipeline_states_namespace, mock_db
    ) -> None:
        """`pipeline_state.get.many()` replaces the old get_libraries_in_state query root."""
        mock_db.aql.execute.return_value = iter(
            [
                {"library_key": "one", "pipeline_state": "library_pipeline_states/scanning"},
                {"library_key": "two", "pipeline_state": "library_pipeline_states/scanning"},
            ],
        )

        assert library_pipeline_states_namespace.pipeline_state.get.many(
            "library_pipeline_states/scanning",
            limit=10,
        ) == [
            {"library_key": "one", "pipeline_state": "library_pipeline_states/scanning"},
            {"library_key": "two", "pipeline_state": "library_pipeline_states/scanning"},
        ]

    @pytest.mark.unit
    def test_library_key_delete_returns_deleted_count(self, library_pipeline_states_namespace, mock_db) -> None:
        """`library_key.delete()` supports cleanup when a library is removed."""
        mock_db.aql.execute.return_value = iter([1])

        assert library_pipeline_states_namespace.library_key.delete("abc123") == 1
