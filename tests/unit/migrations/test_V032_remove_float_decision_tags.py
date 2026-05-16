# ruff: noqa: N999
"""Unit tests for V032 float decision tag removal migration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.migrations.V032_remove_float_decision_tags import (
    MIGRATION_VERSION,
    _collect_float_tag_ids,
    _delete_song_has_tags_edges,
    _delete_tag_vertices,
    _drop_tag_model_output_collection,
    _reset_tag_write_states,
    upgrade,
)


@pytest.mark.unit
@pytest.mark.mocked
class TestMigrationVersion:
    def test_version_is_0_2_32(self) -> None:
        assert MIGRATION_VERSION == "0.2.32"


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectFloatTagIds:
    def test_returns_ids_from_cursor(self) -> None:
        db = MagicMock()
        cursor = MagicMock()
        cursor.__iter__ = MagicMock(return_value=iter(["tags/1", "tags/2"]))
        db.aql.execute.return_value = cursor

        result = _collect_float_tag_ids(db)

        db.aql.execute.assert_called_once()
        query = db.aql.execute.call_args.args[0]
        assert "STARTS_WITH(t.name" in query
        assert "nom:" in query
        assert "IS_NUMBER(t.value)" in query
        assert result == ["tags/1", "tags/2"]

    def test_returns_empty_list_when_no_tags(self) -> None:
        db = MagicMock()
        cursor = MagicMock()
        cursor.__iter__ = MagicMock(return_value=iter([]))
        db.aql.execute.return_value = cursor

        result = _collect_float_tag_ids(db)

        assert result == []


@pytest.mark.unit
@pytest.mark.mocked
class TestDeleteSongHasTagsEdges:
    def test_skips_aql_when_empty_tag_ids(self) -> None:
        db = MagicMock()

        _delete_song_has_tags_edges(db, [])

        db.aql.execute.assert_not_called()

    def test_executes_delete_query_with_batch(self) -> None:
        db = MagicMock()
        cursor = MagicMock()
        cursor.statistics.return_value = {"writesExecuted": 2}
        db.aql.execute.return_value = cursor

        _delete_song_has_tags_edges(db, ["tags/1", "tags/2"])

        db.aql.execute.assert_called_once()
        call_kwargs = db.aql.execute.call_args
        query = call_kwargs.args[0]
        assert "song_has_tags" in query
        assert "REMOVE" in query
        assert call_kwargs.kwargs["bind_vars"] == {"tag_ids": ["tags/1", "tags/2"]}

    def test_batches_large_tag_lists(self) -> None:
        db = MagicMock()
        cursor = MagicMock()
        cursor.statistics.return_value = {"writesExecuted": 0}
        db.aql.execute.return_value = cursor

        # BATCH_SIZE is 500; use 501 to force two calls
        tag_ids = [f"tags/{i}" for i in range(501)]
        _delete_song_has_tags_edges(db, tag_ids)

        assert db.aql.execute.call_count == 2
        first_batch = db.aql.execute.call_args_list[0].kwargs["bind_vars"]["tag_ids"]
        second_batch = db.aql.execute.call_args_list[1].kwargs["bind_vars"]["tag_ids"]
        assert len(first_batch) == 500
        assert len(second_batch) == 1


@pytest.mark.unit
@pytest.mark.mocked
class TestDeleteTagVertices:
    def test_skips_aql_when_empty_tag_ids(self) -> None:
        db = MagicMock()

        _delete_tag_vertices(db, [])

        db.aql.execute.assert_not_called()

    def test_executes_delete_query_with_batch(self) -> None:
        db = MagicMock()
        cursor = MagicMock()
        cursor.statistics.return_value = {"writesExecuted": 3}
        db.aql.execute.return_value = cursor

        _delete_tag_vertices(db, ["tags/1", "tags/2", "tags/3"])

        db.aql.execute.assert_called_once()
        call_kwargs = db.aql.execute.call_args
        query = call_kwargs.args[0]
        assert "FOR t IN tags" in query
        assert "REMOVE t IN tags" in query
        assert call_kwargs.kwargs["bind_vars"] == {"tag_ids": ["tags/1", "tags/2", "tags/3"]}


@pytest.mark.unit
@pytest.mark.mocked
class TestDropTagModelOutputCollection:
    def test_drops_collection_when_present(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True

        _drop_tag_model_output_collection(db)

        db.has_collection.assert_called_once_with("tag_model_output")
        db.delete_collection.assert_called_once_with("tag_model_output")

    def test_skips_drop_when_collection_absent(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False

        _drop_tag_model_output_collection(db)

        db.has_collection.assert_called_once_with("tag_model_output")
        db.delete_collection.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
class TestResetTagWriteStates:
    def test_executes_update_query(self) -> None:
        db = MagicMock()
        cursor = MagicMock()
        cursor.statistics.return_value = {"writesExecuted": 7}
        db.aql.execute.return_value = cursor

        _reset_tag_write_states(db)

        db.aql.execute.assert_called_once()
        query = db.aql.execute.call_args.args[0]
        assert "file_has_state" in query
        assert "tags_written" in query
        assert "tags_not_written" in query

    def test_handles_zero_updates(self) -> None:
        db = MagicMock()
        cursor = MagicMock()
        cursor.statistics.return_value = {"writesExecuted": 0}
        db.aql.execute.return_value = cursor

        _reset_tag_write_states(db)  # must not raise

        db.aql.execute.assert_called_once()


@pytest.mark.unit
@pytest.mark.mocked
class TestUpgrade:
    def test_calls_all_helpers_in_order(self) -> None:
        db = MagicMock()
        cursor = MagicMock()
        cursor.__iter__ = MagicMock(return_value=iter(["tags/1"]))
        cursor.statistics.return_value = {"writesExecuted": 1}
        db.aql.execute.return_value = cursor
        db.has_collection.return_value = False

        upgrade(db)

        # AQL called: collect + delete_edges + delete_vertices + reset_states = 4 calls
        assert db.aql.execute.call_count == 4

    def test_upgrade_with_no_float_tags_skips_deletions(self) -> None:
        db = MagicMock()
        collect_cursor = MagicMock()
        collect_cursor.__iter__ = MagicMock(return_value=iter([]))
        stats_cursor = MagicMock()
        stats_cursor.statistics.return_value = {"writesExecuted": 0}
        db.aql.execute.side_effect = [collect_cursor, stats_cursor]
        db.has_collection.return_value = False

        upgrade(db)

        # Only collect + reset_states - edge/vertex deletions skip when tag_ids empty
        assert db.aql.execute.call_count == 2
