"""Tests for nomarr.persistence.database.tags_aql module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.database.tags_aql import TagsAqlOperations
from nomarr.persistence.schema import CollectionNames


@pytest.mark.unit
@pytest.mark.mocked
def test_replace_file_tags_rebuilds_edges_and_cleans_orphans() -> None:
    ops = TagsAqlOperations(MagicMock())
    tags = [
        {"name": "genre", "value": "rock"},
        {"key": "mood", "value": "calm"},
        {"key": "genre", "value": "rock"},  # duplicate pair — should be deduplicated
    ]
    pair_map = {("genre", "rock"): "tags/genre", ("mood", "calm"): "tags/mood"}

    with (
        patch.object(ops, "_delete_song_tag_edges_for_file") as delete_edges,
        patch.object(ops, "_find_or_create_tags_batch", return_value=pair_map) as find_batch,
        patch("nomarr.persistence.database.tags_aql.tag_edge_ops.primitives.insert_edges_batch") as insert_edges,
        patch.object(ops, "_cleanup_orphaned_tags") as cleanup,
    ):
        ops.replace_file_tags(f"{CollectionNames.LIBRARY_FILES.value}/1", tags)

    delete_edges.assert_called_once_with(f"{CollectionNames.LIBRARY_FILES.value}/1")
    # Only unique pairs passed to batch, deduplication removed the third tag.
    find_batch.assert_called_once_with([("genre", "rock"), ("mood", "calm")])
    insert_edges.assert_called_once()
    edge_docs = insert_edges.call_args[0][2]  # db, collection, edge_docs
    expected = [
        {"_from": f"{CollectionNames.LIBRARY_FILES.value}/1", "_to": "tags/genre"},
        {"_from": f"{CollectionNames.LIBRARY_FILES.value}/1", "_to": "tags/mood"},
    ]
    assert edge_docs == expected
    cleanup.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.mocked
def test_replace_tag_references_moves_edges_and_cleans_orphans() -> None:
    ops = TagsAqlOperations(MagicMock())
    candidate_edges = [
        {"_id": "song_has_tag/1", "_from": f"{CollectionNames.LIBRARY_FILES.value}/1", "_to": "tags/source"},
        {"_id": "song_has_tag/2", "_from": f"{CollectionNames.LIBRARY_FILES.value}/2", "_to": "tags/source"},
        {"_id": "song_has_tag/3", "_from": f"{CollectionNames.LIBRARY_FILES.value}/2", "_to": "tags/target"},
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
            file_ids=[f"{CollectionNames.LIBRARY_FILES.value}/1", f"{CollectionNames.LIBRARY_FILES.value}/2"],
        )

    get_edges.assert_called_once_with(["tags/source", "tags/target"])
    insert_edges.assert_called_once_with([{"_from": f"{CollectionNames.LIBRARY_FILES.value}/1", "_to": "tags/target"}])
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
        ops.remove_file_tags(f"{CollectionNames.LIBRARY_FILES.value}/1", ["genre"])

    get_rows.assert_called_once_with([f"{CollectionNames.LIBRARY_FILES.value}/1"], include_edge=True)
    delete_edge.assert_called_once_with("song_has_tag/genre")
    cleanup.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.mocked
def test_get_orphaned_tag_ids_filters_only_on_song_edges() -> None:
    db = MagicMock()
    ops = TagsAqlOperations(db)

    with patch(
        "nomarr.persistence.database.tags_aql.tag_edge_ops.primitives.execute",
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


@pytest.mark.unit
@pytest.mark.mocked
def test_search_files_by_tag_contains_uses_in_operator() -> None:
    """CONTAINS query should use @value IN tag.value for array matching."""
    db = MagicMock()
    ops = TagsAqlOperations(db)
    expected_files = [
        {"_id": f"{CollectionNames.LIBRARY_FILES.value}/1"},
        {"_id": f"{CollectionNames.LIBRARY_FILES.value}/2"},
    ]

    with patch(
        "nomarr.persistence.database.tags_aql.tag_search_ops.primitives.execute",
        return_value=expected_files,
    ) as execute:
        result = ops.search_files_by_tag_contains("nom:mood-strict", "aggressive", limit=None)

    execute.assert_called_once()
    assert execute.call_args.args[0] is db
    query = execute.call_args.args[1]
    bind_vars = execute.call_args.args[2]

    # Verify the query uses IN operator for array containment
    assert "@value IN tag.value" in query
    assert "tag.name == @tag_key" in query
    assert bind_vars["tag_key"] == "nom:mood-strict"
    assert bind_vars["value"] == "aggressive"
    assert bind_vars["@tag_collection"] == TagsAqlOperations.COLLECTION
    assert bind_vars["@edge_collection"] == TagsAqlOperations.EDGE_COLLECTION
    assert result == expected_files


@pytest.mark.unit
@pytest.mark.mocked
def test_search_files_by_tag_contains_respects_limit() -> None:
    """CONTAINS query should apply LIMIT when specified."""
    db = MagicMock()
    ops = TagsAqlOperations(db)

    with patch(
        "nomarr.persistence.database.tags_aql.tag_search_ops.primitives.execute",
        return_value=[{"_id": f"{CollectionNames.LIBRARY_FILES.value}/1"}],
    ) as execute:
        ops.search_files_by_tag_contains("nom:mood-strict", "happy", limit=10)

    query = execute.call_args.args[1]
    bind_vars = execute.call_args.args[2]

    assert "LIMIT @limit" in query
    assert bind_vars["limit"] == 10
