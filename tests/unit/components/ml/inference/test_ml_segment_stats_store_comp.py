"""Tests for nomarr.components.ml.inference.ml_segment_stats_store_comp module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.inference.ml_segment_stats_store_comp import (
    _edge_key,
    _stats_key,
    delete_segment_stats_for_file,
    delete_segment_stats_for_files,
    get_segment_stats_for_file,
    get_segment_stats_for_files_bulk,
    upsert_segment_stats_batch,
)
from nomarr.persistence.base import Field


@pytest.mark.unit
@pytest.mark.mocked
class TestUpsertSegmentStatsBatch:
    """Tests for ``upsert_segment_stats_batch``."""

    def test_returns_early_for_empty_entries(self) -> None:
        mock_db = MagicMock()

        upsert_segment_stats_batch(mock_db, [])

        mock_db.segment_scores_stats.upsert_batch.assert_not_called()
        mock_db.file_has_segment_stats.get.in_.assert_not_called()
        mock_db.file_has_segment_stats.insert.assert_not_called()

    def test_bulk_upserts_docs_and_only_inserts_missing_edges(self) -> None:
        mock_db = MagicMock()
        timestamp = 123456789
        file1 = "library_files/file-1"
        file2 = "library_files/file-2"
        mood_id = f"segment_scores_stats/{_stats_key(file1, 'mood', 'v1')}"
        energy_id = f"segment_scores_stats/{_stats_key(file1, 'energy', 'v1')}"
        genre_id = f"segment_scores_stats/{_stats_key(file2, 'genre', 'v2')}"
        mock_db.file_has_segment_stats.get.in_.return_value = [
            {"_from": file1, "_to": mood_id},
            {"_from": file1, "_to": "segment_scores_stats/unrelated"},
        ]
        entries = [
            {
                "file_id": file1,
                "head_name": "mood",
                "tagger_version": "v1",
                "num_segments": 12,
                "pooling_strategy": "mean",
                "label_stats": [{"label": "calm", "mean": 0.1}],
                "processed_at": 111,
            },
            {
                "file_id": file1,
                "head_name": "energy",
                "tagger_version": "v1",
                "num_segments": 12,
                "pooling_strategy": "mean",
                "label_stats": [{"label": "high", "mean": 0.9}],
            },
            {
                "file_id": file2,
                "head_name": "genre",
                "tagger_version": "v2",
                "num_segments": 8,
                "pooling_strategy": "max",
                "label_stats": [{"label": "rock", "mean": 0.7}],
            },
        ]

        with patch(
            "nomarr.components.ml.inference.ml_segment_stats_store_comp.now_ms",
            return_value=SimpleNamespace(value=timestamp),
        ):
            upsert_segment_stats_batch(mock_db, entries)

        mock_db.segment_scores_stats.upsert_batch.assert_called_once()
        upsert_docs = mock_db.segment_scores_stats.upsert_batch.call_args.args[0]
        assert mock_db.segment_scores_stats.upsert_batch.call_args.kwargs == {"match_fields": "_key"}
        assert upsert_docs == [
            {
                "_key": _stats_key(file1, "mood", "v1"),
                "head_name": "mood",
                "tagger_version": "v1",
                "num_segments": 12,
                "pooling_strategy": "mean",
                "label_stats": [{"label": "calm", "mean": 0.1}],
                "processed_at": 111,
            },
            {
                "_key": _stats_key(file1, "energy", "v1"),
                "head_name": "energy",
                "tagger_version": "v1",
                "num_segments": 12,
                "pooling_strategy": "mean",
                "label_stats": [{"label": "high", "mean": 0.9}],
                "processed_at": timestamp,
            },
            {
                "_key": _stats_key(file2, "genre", "v2"),
                "head_name": "genre",
                "tagger_version": "v2",
                "num_segments": 8,
                "pooling_strategy": "max",
                "label_stats": [{"label": "rock", "mean": 0.7}],
                "processed_at": timestamp,
            },
        ]
        mock_db.file_has_segment_stats.get.in_.assert_called_once_with(
            Field("_from", [file1, file2]),
            limit=None,
        )
        mock_db.file_has_segment_stats.insert.assert_called_once_with(
            [
                {"_key": _edge_key(file1, energy_id), "_from": file1, "_to": energy_id},
                {"_key": _edge_key(file2, genre_id), "_from": file2, "_to": genre_id},
            ]
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestGetSegmentStatsForFilesBulk:
    """Tests for grouped traversal-backed reads."""

    def test_returns_empty_for_empty_file_ids(self) -> None:
        mock_db = MagicMock()

        result = get_segment_stats_for_files_bulk(mock_db, [])

        assert result == {}
        mock_db.library_files.file_has_segment_stats.by_ids.assert_not_called()

    def test_groups_rows_by_file_id_in_input_order(self) -> None:
        mock_db = MagicMock()
        file1 = "library_files/file-1"
        file2 = "library_files/file-2"
        file3 = "library_files/file-3"
        stats1 = {"_id": "segment_scores_stats/1", "head_name": "mood"}
        stats2a = {"_id": "segment_scores_stats/2a", "head_name": "genre"}
        stats2b = {"_id": "segment_scores_stats/2b", "head_name": "energy"}
        mock_db.library_files.file_has_segment_stats.by_ids.return_value = [
            {"start_id": file1, "v": stats1},
            {"start_id": file2, "v": stats2a},
            {"start_id": file2, "v": stats2b},
            {"start_id": file3, "v": "ignored-non-doc"},
        ]

        result = get_segment_stats_for_files_bulk(mock_db, [file2, file1, file2, file3])

        assert result == {file2: [stats2a, stats2b], file1: [stats1]}
        assert list(result.keys()) == [file2, file1]
        mock_db.library_files.file_has_segment_stats.by_ids.assert_called_once_with([file2, file1, file3], limit=None)


@pytest.mark.unit
@pytest.mark.mocked
class TestGetSegmentStatsForFile:
    """Tests for the singleton wrapper around grouped reads."""

    def test_returns_single_file_stats_from_bulk_reader(self) -> None:
        mock_db = MagicMock()
        file_id = "library_files/file-7"
        stats_docs = [
            {"_id": "segment_scores_stats/7a", "head_name": "mood"},
            {"_id": "segment_scores_stats/7b", "head_name": "genre"},
        ]
        mock_db.library_files.file_has_segment_stats.by_ids.return_value = [
            {"start_id": file_id, "v": stats_docs[0]},
            {"start_id": file_id, "v": stats_docs[1]},
        ]

        result = get_segment_stats_for_file(mock_db, file_id)

        assert result == stats_docs
        mock_db.library_files.file_has_segment_stats.by_ids.assert_called_once_with([file_id], limit=None)


@pytest.mark.unit
@pytest.mark.mocked
class TestDeleteSegmentStatsForFiles:
    """Tests for grouped cascade deletes."""

    def test_returns_zero_for_empty_file_ids(self) -> None:
        mock_db = MagicMock()

        result = delete_segment_stats_for_files(mock_db, [])

        assert result == 0
        mock_db.library_files.file_has_segment_stats.by_ids.assert_not_called()
        mock_db.segment_scores_stats.delete.cascade.assert_not_called()

    def test_returns_zero_when_grouped_stats_have_no_ids(self) -> None:
        mock_db = MagicMock()
        file_id = "library_files/file-2"
        mock_db.library_files.file_has_segment_stats.by_ids.return_value = [
            {"start_id": file_id, "v": {"head_name": "mood"}},
            {"start_id": file_id, "v": {"label_stats": []}},
        ]

        result = delete_segment_stats_for_files(mock_db, [file_id])

        assert result == 0
        mock_db.library_files.file_has_segment_stats.by_ids.assert_called_once_with([file_id], limit=None)
        mock_db.segment_scores_stats.delete.cascade.assert_not_called()

    def test_cascades_grouped_stats_ids_once(self) -> None:
        mock_db = MagicMock()
        file1 = "library_files/file-1"
        file2 = "library_files/file-2"
        mock_db.library_files.file_has_segment_stats.by_ids.return_value = [
            {"start_id": file2, "v": {"_id": "segment_scores_stats/stats-2", "head_name": "genre"}},
            {"start_id": file1, "v": {"_id": "segment_scores_stats/stats-1", "head_name": "mood"}},
            {"start_id": file2, "v": {"_id": "segment_scores_stats/stats-3", "head_name": "energy"}},
        ]
        mock_db.segment_scores_stats.delete.cascade.return_value = 3

        result = delete_segment_stats_for_files(mock_db, [file1, file2])

        assert result == 3
        mock_db.library_files.file_has_segment_stats.by_ids.assert_called_once_with([file1, file2], limit=None)
        mock_db.segment_scores_stats.delete.cascade.assert_called_once_with(
            [
                "segment_scores_stats/stats-1",
                "segment_scores_stats/stats-2",
                "segment_scores_stats/stats-3",
            ]
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestDeleteSegmentStatsForFile:
    """Tests for the singleton wrapper around grouped cascade deletes."""

    def test_delegates_to_grouped_delete_path(self) -> None:
        mock_db = MagicMock()
        file_id = "library_files/file-9"
        mock_db.library_files.file_has_segment_stats.by_ids.return_value = [
            {"start_id": file_id, "v": {"_id": "segment_scores_stats/stats-9a", "head_name": "mood"}},
            {"start_id": file_id, "v": {"_id": "segment_scores_stats/stats-9b", "head_name": "genre"}},
        ]
        mock_db.segment_scores_stats.delete.cascade.return_value = 2

        result = delete_segment_stats_for_file(mock_db, file_id)

        assert result == 2
        mock_db.library_files.file_has_segment_stats.by_ids.assert_called_once_with([file_id], limit=None)
        mock_db.segment_scores_stats.delete.cascade.assert_called_once_with(
            ["segment_scores_stats/stats-9a", "segment_scores_stats/stats-9b"]
        )
