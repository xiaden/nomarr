"""Unit tests for _discover_template_collections in prepare_database_wf."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.workflows.platform.prepare_database_wf import _discover_template_collections


class TestDiscoverTemplateCollections:
    """Tests for _discover_template_collections()."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_collection_matching_template_hot_prefix(self) -> None:
        """Collections starting with vectors_track_hot__ are registered with correct template."""
        db = MagicMock()
        db.db.collections.return_value = [
            {"name": "vectors_track_hot__effnet__lib1"},
        ]

        _discover_template_collections(db)

        db.register.assert_called_once_with("vectors_track_hot__effnet__lib1", "vectors_track_hot")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_collection_matching_template_cold_prefix(self) -> None:
        """Collections starting with vectors_track_cold__ are registered with correct template."""
        db = MagicMock()
        db.db.collections.return_value = [
            {"name": "vectors_track_cold__effnet__lib1"},
        ]

        _discover_template_collections(db)

        db.register.assert_called_once_with("vectors_track_cold__effnet__lib1", "vectors_track_cold")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_system_collections(self) -> None:
        """Collections starting with '_' (ArangoDB internal) are never registered."""
        db = MagicMock()
        db.db.collections.return_value = [
            {"name": "_system"},
            {"name": "_graphs"},
            {"name": "_users"},
        ]

        _discover_template_collections(db)

        db.register.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_non_template_named_collections(self) -> None:
        """Regular collections that share no prefix with any TEMPLATE are not registered."""
        db = MagicMock()
        db.db.collections.return_value = [
            {"name": "libraries"},
            {"name": "library_files"},
            {"name": "tags"},
            {"name": "migrations"},
        ]

        _discover_template_collections(db)

        db.register.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_swallows_value_error_and_continues_with_next_collection(self) -> None:
        """ValueError from register() is caught; remaining collections are still processed."""
        db = MagicMock()
        db.db.collections.return_value = [
            {"name": "vectors_track_hot__effnet__lib1"},
            {"name": "vectors_track_hot__yamnet__lib1"},
        ]
        db.register.side_effect = [ValueError("collection missing in ArangoDB"), None]

        _discover_template_collections(db)  # must not propagate ValueError

        assert db.register.call_count == 2
        db.register.assert_any_call("vectors_track_hot__yamnet__lib1", "vectors_track_hot")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_registers_multiple_matching_collections_across_templates(self) -> None:
        """Multiple matching collections across different templates are all registered."""
        db = MagicMock()
        db.db.collections.return_value = [
            {"name": "vectors_track_hot__effnet__lib1"},
            {"name": "vectors_track_cold__effnet__lib1"},
            {"name": "libraries"},
        ]

        _discover_template_collections(db)

        assert db.register.call_count == 2
        db.register.assert_any_call("vectors_track_hot__effnet__lib1", "vectors_track_hot")
        db.register.assert_any_call("vectors_track_cold__effnet__lib1", "vectors_track_cold")
