"""Tests for nomarr.components.tagging.tag_cleanup_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.tagging.tag_cleanup_comp import (
    cleanup_orphaned_tags,
    get_orphaned_tag_count,
)


def _make_cleanup_db(
    *,
    all_tag_ids: list[str],
    song_edge_targets: list[str],
    model_edge_sources: list[str],
    cascade_result: int = 0,
) -> MagicMock:
    """Build a tagging db mock for orphan cleanup tests."""
    mock_db = MagicMock()
    mock_db.tags.count.return_value = len(all_tag_ids)
    mock_db.tags.aggregate.return_value = [{"value": tag_id} for tag_id in all_tag_ids]
    mock_db.song_has_tags.count.return_value = len(song_edge_targets)
    mock_db.library_files.aggregate.return_value = [{"value": tag_id} for tag_id in song_edge_targets]
    mock_db.tag_model_output.count.return_value = len(model_edge_sources)
    mock_db.tag_model_output.aggregate.return_value = [{"value": tag_id} for tag_id in model_edge_sources]
    mock_db.tags.delete.cascade.return_value = cascade_result
    return mock_db


class TestCleanupOrphanedTags:
    """Tests for cleanup_orphaned_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_and_skips_cascade_when_no_tags_exist(self) -> None:
        mock_db = _make_cleanup_db(
            all_tag_ids=[],
            song_edge_targets=[],
            model_edge_sources=[],
        )

        result = cleanup_orphaned_tags(mock_db)

        assert result == 0
        mock_db.tags.delete.cascade.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_all_tags_are_used_by_song_edges(self) -> None:
        mock_db = _make_cleanup_db(
            all_tag_ids=["tags/1", "tags/2", "tags/3"],
            song_edge_targets=["tags/1", "tags/2", "tags/3"],
            model_edge_sources=[],
        )

        result = cleanup_orphaned_tags(mock_db)

        assert result == 0
        mock_db.tags.delete.cascade.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_cascades_orphan_ids_and_returns_deleted_count(self) -> None:
        mock_db = _make_cleanup_db(
            all_tag_ids=["tags/1", "tags/2", "tags/3", "tags/4"],
            song_edge_targets=["tags/1"],
            model_edge_sources=["tags/2"],
            cascade_result=2,
        )

        result = cleanup_orphaned_tags(mock_db)

        assert result == 2
        assert mock_db.tags.delete.cascade.call_count == 1
        cascaded_ids = set(mock_db.tags.delete.cascade.call_args[0][0])
        assert cascaded_ids == {"tags/3", "tags/4"}


class TestGetOrphanedTagCount:
    """Tests for get_orphaned_tag_count."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_no_tags_exist(self) -> None:
        mock_db = _make_cleanup_db(
            all_tag_ids=[],
            song_edge_targets=[],
            model_edge_sources=[],
        )

        result = get_orphaned_tag_count(mock_db)

        assert result == 0

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_count_of_unreferenced_tags(self) -> None:
        mock_db = _make_cleanup_db(
            all_tag_ids=["tags/1", "tags/2", "tags/3", "tags/4"],
            song_edge_targets=["tags/1", "tags/2"],
            model_edge_sources=["tags/4"],
        )

        result = get_orphaned_tag_count(mock_db)

        assert result == 1

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_excludes_tags_referenced_by_model_output_edges(self) -> None:
        mock_db = _make_cleanup_db(
            all_tag_ids=["tags/1", "tags/2", "tags/3"],
            song_edge_targets=["tags/1", "tags/2"],
            model_edge_sources=["tags/3"],
        )

        result = get_orphaned_tag_count(mock_db)

        assert result == 0
