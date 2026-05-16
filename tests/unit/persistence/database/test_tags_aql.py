"""Tests for nomarr.persistence.database.tags_aql module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.database.tags_aql import TagsAqlOperations


class TestAggregateTagField:
    """Tests for TagsAqlOperations.aggregate_tag_field."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_allows_underscore_id_field(self) -> None:
        mock_safe_db = MagicMock()
        mock_safe_db.aql.execute.return_value = [{"value": "tags/1", "count": 1}]
        ops = TagsAqlOperations(mock_safe_db)

        result = ops.aggregate_tag_field("_id", limit=5, offset=2)

        assert result == [{"value": "tags/1", "count": 1}]
        mock_safe_db.aql.execute.assert_called_once()
        query = mock_safe_db.aql.execute.call_args.kwargs["bind_vars"]
        assert query == {"@collection": "tags", "offset": 2, "limit": 5}


@pytest.mark.unit
@pytest.mark.mocked
def test_replace_file_tags_rebuilds_edges_and_cleans_orphans() -> None:
    ops = TagsAqlOperations(MagicMock())
    tags = [
        {"name": "genre", "value": "rock"},
        {"key": "mood", "value": "calm"},
    ]

    with (
        patch.object(ops, "_delete_song_tag_edges_for_file") as delete_edges,
        patch.object(ops, "_find_or_create_tag", side_effect=["tags/genre", "tags/mood"]) as find_or_create,
        patch.object(ops, "_upsert_song_tag_edge") as upsert_edge,
        patch.object(ops, "_cleanup_orphaned_tags") as cleanup,
    ):
        ops.replace_file_tags("library_files/1", tags)

    delete_edges.assert_called_once_with("library_files/1")
    assert find_or_create.call_args_list == [
        (("genre", "rock"), {}),
        (("mood", "calm"), {}),
    ]
    assert upsert_edge.call_args_list == [
        (("library_files/1", "tags/genre"), {}),
        (("library_files/1", "tags/mood"), {}),
    ]
    cleanup.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.mocked
def test_replace_tag_references_moves_edges_and_cleans_orphans() -> None:
    ops = TagsAqlOperations(MagicMock())
    candidate_edges = [
        {"_id": "song_has_tag/1", "_from": "library_files/1", "_to": "tags/source"},
        {"_id": "song_has_tag/2", "_from": "library_files/2", "_to": "tags/source"},
        {"_id": "song_has_tag/3", "_from": "library_files/2", "_to": "tags/target"},
    ]

    with (
        patch.object(ops, "_get_song_tag_edges_for_tags", return_value=candidate_edges) as get_edges,
        patch.object(ops, "_insert_song_tag_edges") as insert_edges,
        patch.object(ops, "_delete_song_tag_edge_by_id") as delete_edge,
        patch.object(ops, "_count_song_tag_edges", return_value=0) as count_edges,
        patch.object(ops, "_cleanup_orphaned_tags") as cleanup,
    ):
        ops.replace_tag_references(
            "tags/source",
            "tags/target",
            file_ids=["library_files/1", "library_files/2"],
        )

    get_edges.assert_called_once_with(["tags/source", "tags/target"])
    insert_edges.assert_called_once_with([{"_from": "library_files/1", "_to": "tags/target"}])
    assert delete_edge.call_args_list == [(("song_has_tag/1",), {}), (("song_has_tag/2",), {})]
    count_edges.assert_called_once_with("tags/source")
    cleanup.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.mocked
def test_remove_file_tags_deletes_selected_edges_then_cleans_orphans() -> None:
    ops = TagsAqlOperations(MagicMock())
    rows = [
        {"v": {"name": "genre"}, "e": {"_id": "song_has_tag/genre"}},
        {"v": {"name": "mood"}, "e": {"_id": "song_has_tag/mood"}},
    ]

    with (
        patch.object(ops, "get_tags_for_files_batch", return_value=rows) as get_rows,
        patch.object(ops, "_delete_song_tag_edge_by_id") as delete_edge,
        patch.object(ops, "_cleanup_orphaned_tags") as cleanup,
    ):
        ops.remove_file_tags("library_files/1", ["genre"])

    get_rows.assert_called_once_with(["library_files/1"], include_edge=True)
    delete_edge.assert_called_once_with("song_has_tag/genre")
    cleanup.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.mocked
def test_get_orphaned_tag_ids_filters_only_on_song_edges() -> None:
    db = MagicMock()
    ops = TagsAqlOperations(db)

    with patch(
        "nomarr.persistence.database.tags_aql.primitives.execute",
        return_value=["tags/1", "tags/2"],
    ) as execute:
        result = ops.get_orphaned_tag_ids()

    execute.assert_called_once()
    assert execute.call_args.args[0] is db
    query = execute.call_args.args[1]
    bind_vars = execute.call_args.args[2]
    assert "tag_model_output" not in query
    assert "model_output" not in query
    assert "@@song_edge_collection" in query
    assert bind_vars["@tag_collection"] == TagsAqlOperations.COLLECTION
    assert bind_vars["@song_edge_collection"] == TagsAqlOperations.EDGE_COLLECTION
    assert result == ["tags/1", "tags/2"]
