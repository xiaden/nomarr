# ruff: noqa: N999
"""Unit tests for V031 legacy library_files cleanup migration."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from nomarr.migrations.V031_remove_legacy_library_file_fields import upgrade


@pytest.mark.unit
@pytest.mark.mocked
class TestV031RemoveLegacyLibraryFileFields:
    """Tests for dropping stale library_files indexes and state-ish fields."""

    def test_drops_known_legacy_indexes_and_removes_fields(self) -> None:
        db = MagicMock()
        coll = MagicMock()
        db.collection.return_value = coll
        coll.indexes.return_value = [
            {"id": "idx/library_id", "fields": ["library_id"]},
            {"id": "idx/lib_tagged", "fields": ["library_id", "tagged"]},
            {"id": "idx/current", "fields": ["normalized_path"]},
        ]

        upgrade(db)

        db.collection.assert_called_once_with("library_files")
        coll.delete_index.assert_has_calls([call("idx/library_id"), call("idx/lib_tagged")])
        assert coll.delete_index.call_count == 2
        db.aql.execute.assert_called_once()
        query = db.aql.execute.call_args.args[0]
        assert "FOR doc IN library_files" in query
        assert "HAS(doc, 'needs_tagging')" in query
        assert "HAS(doc, 'tagged')" in query
        assert "OPTIONS { keepNull: false }" in query

    def test_safe_rerun_skips_when_only_current_indexes_exist(self) -> None:
        db = MagicMock()
        coll = MagicMock()
        db.collection.return_value = coll
        coll.indexes.return_value = [
            {"id": "idx/current", "fields": ["normalized_path"]},
            {"id": "idx/path", "fields": ["path"]},
        ]

        upgrade(db)

        coll.delete_index.assert_not_called()
        db.aql.execute.assert_called_once()
