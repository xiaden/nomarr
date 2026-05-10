"""Tests for persistence AQL primitives."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.aql.primitives import (
    count_distinct_edge_sources_to_filtered_vertices,
    delete_many_by_keys,
    execute,
    get_filtered_docs,
    get_many_by_field,
    get_many_by_keys,
    insert_document,
    list_field_values,
    normalize_limit,
    update_document_by_key,
    upsert_by_field,
)


@pytest.mark.unit
@pytest.mark.mocked
class TestNormalizeLimit:
    def test_returns_large_limit_for_none(self) -> None:
        assert normalize_limit(None) == 2**31 - 1

    def test_clamps_negative_to_zero(self) -> None:
        assert normalize_limit(-3) == 0


@pytest.mark.unit
@pytest.mark.mocked
class TestExecute:
    def test_materializes_execute_cursor(self) -> None:
        db = MagicMock()
        with patch("nomarr.persistence.aql.primitives._execute_aql", return_value=iter([{"_id": "1"}, {"_id": "2"}])) as execute_mock:
            result = execute(db, "FOR d IN c RETURN d", {"x": 1})

        assert result == [{"_id": "1"}, {"_id": "2"}]
        execute_mock.assert_called_once_with(db, "FOR d IN c RETURN d", bind_vars={"x": 1})

    def test_propagates_execute_errors(self) -> None:
        db = MagicMock()
        with (
            patch("nomarr.persistence.aql.primitives._execute_aql", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            execute(db, "FOR d IN c RETURN d", {"x": 1})


@pytest.mark.unit
@pytest.mark.mocked
class TestPrimitiveVerbs:
    def test_get_many_by_keys_returns_only_dict_rows(self) -> None:
        db = MagicMock()
        with patch("nomarr.persistence.aql.primitives.execute", return_value=[{"_key": "1"}, "bad"]):
            result = get_many_by_keys(db, "library_files", ["1"])
        assert result == [{"_key": "1"}]

    def test_get_many_by_field_returns_only_dict_rows(self) -> None:
        db = MagicMock()
        with patch("nomarr.persistence.aql.primitives.execute", return_value=[{"_key": "1"}, 1]):
            result = get_many_by_field(db, "tags", "name", "genre")
        assert result == [{"_key": "1"}]

    def test_get_many_by_field_rejects_invalid_field_name(self) -> None:
        db = MagicMock()
        with pytest.raises(ValueError, match="Invalid field name"):
            get_many_by_field(db, "tags", "name; DROP", "genre")

    def test_get_filtered_docs_returns_only_dict_rows(self) -> None:
        db = MagicMock()
        with patch("nomarr.persistence.aql.primitives.execute", return_value=[{"_id": "libraries/1"}, "bad"]):
            result = get_filtered_docs(db, "libraries", filters={"is_enabled": True}, allowed_fields={"is_enabled"})
        assert result == [{"_id": "libraries/1"}]

    def test_list_field_values_returns_raw_rows(self) -> None:
        db = MagicMock()
        with patch("nomarr.persistence.aql.primitives.execute", return_value=["libraries/1", 1]):
            result = list_field_values(db, "library_files", "_id", allowed_fields={"_id"})
        assert result == ["libraries/1", 1]

    def test_count_distinct_edge_sources_to_filtered_vertices_returns_count(self) -> None:
        db = MagicMock()
        with patch("nomarr.persistence.aql.primitives.execute", return_value=[3]):
            result = count_distinct_edge_sources_to_filtered_vertices(
                db,
                edge_collection="song_has_tags",
                edge_source_field="_from",
                edge_target_field="_to",
                vertex_collection="tags",
                vertex_filters={"name": "genre"},
                vertex_allowed_fields={"name"},
                edge_allowed_fields={"_from", "_to"},
            )
        assert result == 3

    def test_delete_many_by_keys_returns_count(self) -> None:
        db = MagicMock()
        with patch("nomarr.persistence.aql.primitives.execute", return_value=[2]):
            result = delete_many_by_keys(db, "tags", ["1", "2"])
        assert result == 2

    def test_upsert_by_field_returns_id_rows_only(self) -> None:
        db = MagicMock()
        with patch("nomarr.persistence.aql.primitives.execute", return_value=["tags/1", {"bad": True}]):
            result = upsert_by_field(db, "tags", "name", "genre", {"value": "rock"})
        assert result == ["tags/1"]

    def test_insert_document_returns_inserted_id(self) -> None:
        db = MagicMock()
        with patch("nomarr.persistence.aql.primitives.execute", return_value=["libraries/1"]):
            result = insert_document(db, "libraries", {"name": "Main"})
        assert result == "libraries/1"

    def test_update_document_by_key_executes_without_return(self) -> None:
        db = MagicMock()
        with patch("nomarr.persistence.aql.primitives.execute") as execute_mock:
            update_document_by_key(db, "libraries", "main", {"is_enabled": True})
        _, _, bind_vars = execute_mock.call_args.args
        assert bind_vars["key"] == "main"
