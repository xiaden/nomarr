"""Unit tests for _discover_template_collections in prepare_database_wf."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.workflows.platform.prepare_database_wf import _discover_template_collections, _is_fresh_database


class TestDiscoverTemplateCollections:
    """Tests for _discover_template_collections()."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_collection_matching_template_hot_prefix(self) -> None:
        """Collections starting with vectors_track_hot__ are registered with correct template."""
        db = MagicMock()
        db.app.list_collections.return_value = [
            "vectors_track_hot__effnet__lib1",
        ]

        _discover_template_collections(db)

        db.ml.add_vector_collection.assert_called_once_with("vectors_track_hot__effnet__lib1", "vectors_track_hot")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_collection_matching_template_cold_prefix(self) -> None:
        """Collections starting with vectors_track_cold__ are registered with correct template."""
        db = MagicMock()
        db.app.list_collections.return_value = [
            "vectors_track_cold__effnet__lib1",
        ]

        _discover_template_collections(db)

        db.ml.add_vector_collection.assert_called_once_with("vectors_track_cold__effnet__lib1", "vectors_track_cold")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_system_collections(self) -> None:
        """Collections starting with '_' (ArangoDB internal) are never registered."""
        db = MagicMock()
        db.app.list_collections.return_value = [
            "_system",
            "_graphs",
            "_users",
        ]

        _discover_template_collections(db)

        db.ml.add_vector_collection.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_non_template_named_collections(self) -> None:
        """Regular collections that share no prefix with any TEMPLATE are not registered."""
        db = MagicMock()
        db.app.list_collections.return_value = [
            "libraries",
            "library_files",
            "tags",
            "applied_migrations",
        ]

        _discover_template_collections(db)

        db.ml.add_vector_collection.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_swallows_value_error_and_continues_with_next_collection(self) -> None:
        """ValueError from register() is caught; remaining collections are still processed."""
        db = MagicMock()
        db.app.list_collections.return_value = [
            "vectors_track_hot__effnet__lib1",
            "vectors_track_hot__yamnet__lib1",
        ]
        db.ml.add_vector_collection.side_effect = [ValueError("collection missing in ArangoDB"), None]

        _discover_template_collections(db)  # must not propagate ValueError

        assert db.ml.add_vector_collection.call_count == 2
        db.ml.add_vector_collection.assert_any_call("vectors_track_hot__yamnet__lib1", "vectors_track_hot")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_multiple_matching_collections_across_templates(self) -> None:
        """Multiple matching collections across different templates are all registered."""
        db = MagicMock()
        db.app.list_collections.return_value = [
            "vectors_track_hot__effnet__lib1",
            "vectors_track_cold__effnet__lib1",
            "libraries",
        ]

        _discover_template_collections(db)

        assert db.ml.add_vector_collection.call_count == 2
        db.ml.add_vector_collection.assert_any_call("vectors_track_hot__effnet__lib1", "vectors_track_hot")
        db.ml.add_vector_collection.assert_any_call("vectors_track_cold__effnet__lib1", "vectors_track_cold")


class TestIsFreshDatabase:
    """Tests for _is_fresh_database()."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_true_when_version_entry_missing(self) -> None:
        """No version document in meta means fresh database."""
        db = MagicMock()
        db.app.get_schema_version.return_value = None

        assert _is_fresh_database(db) is True
        db.app.get_schema_version.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_version_entry_exists(self) -> None:
        """Existing version document means existing (not fresh) database."""
        db = MagicMock()
        db.app.get_schema_version.return_value = "028"

        assert _is_fresh_database(db) is False
        db.app.get_schema_version.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_propagates_exception_from_get_schema_version(self) -> None:
        """Exceptions from get_schema_version propagate to the caller."""
        db = MagicMock()
        db.app.get_schema_version.side_effect = RuntimeError("db unavailable")

        with pytest.raises(RuntimeError):
            _is_fresh_database(db)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_for_any_non_none_version(self) -> None:
        """Any non-None value from get_schema_version means an existing database."""
        db = MagicMock()
        db.app.get_schema_version.return_value = "001"

        assert _is_fresh_database(db) is False
        db.app.get_schema_version.assert_called_once_with()
