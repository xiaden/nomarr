"""Tests for nomarr.components.ml.inference.ml_segment_stats_store_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.inference.ml_segment_stats_store_comp import (
    delete_segment_stats_for_file,
    delete_segment_stats_for_files,
)


@pytest.mark.unit
@pytest.mark.mocked
class TestDeleteSegmentStatsForFile:
    """Tests for ``delete_segment_stats_for_file``."""

    def test_returns_zero_when_no_stats_docs_exist(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.ml.inference.ml_segment_stats_store_comp.get_segment_stats_for_file",
            return_value=[],
        ) as mock_get_segment_stats:
            result = delete_segment_stats_for_file(mock_db, "library_files/file-1")

        assert result == 0
        mock_get_segment_stats.assert_called_once_with(mock_db, "library_files/file-1")
        mock_db.segment_scores_stats.delete.cascade.assert_not_called()

    def test_returns_zero_when_stats_docs_have_no_ids(self) -> None:
        mock_db = MagicMock()
        stats_docs = [{"head_name": "mood"}, {"label_stats": []}]

        with patch(
            "nomarr.components.ml.inference.ml_segment_stats_store_comp.get_segment_stats_for_file",
            return_value=stats_docs,
        ) as mock_get_segment_stats:
            result = delete_segment_stats_for_file(mock_db, "library_files/file-2")

        assert result == 0
        mock_get_segment_stats.assert_called_once_with(mock_db, "library_files/file-2")
        mock_db.segment_scores_stats.delete.cascade.assert_not_called()

    def test_cascades_stats_ids_as_list_and_returns_deleted_count(self) -> None:
        mock_db = MagicMock()
        mock_db.segment_scores_stats.delete.cascade.return_value = 3
        stats_docs = [
            {"_id": "segment_scores_stats/stats-1", "head_name": "mood"},
            {"_id": "segment_scores_stats/stats-2", "head_name": "genre"},
            {"head_name": "ignored-without-id"},
            {"_id": "segment_scores_stats/stats-3", "head_name": "energy"},
        ]

        with patch(
            "nomarr.components.ml.inference.ml_segment_stats_store_comp.get_segment_stats_for_file",
            return_value=stats_docs,
        ) as mock_get_segment_stats:
            result = delete_segment_stats_for_file(mock_db, "library_files/file-3")

        assert result == 3
        mock_get_segment_stats.assert_called_once_with(mock_db, "library_files/file-3")
        assert mock_db.segment_scores_stats.delete.cascade.call_count == 1
        cascaded_ids = mock_db.segment_scores_stats.delete.cascade.call_args.args[0]
        assert isinstance(cascaded_ids, list)
        assert cascaded_ids == [
            "segment_scores_stats/stats-1",
            "segment_scores_stats/stats-2",
            "segment_scores_stats/stats-3",
        ]


@pytest.mark.unit
@pytest.mark.mocked
class TestDeleteSegmentStatsForFiles:
    """Tests for ``delete_segment_stats_for_files``."""

    def test_returns_zero_for_empty_file_ids(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.ml.inference.ml_segment_stats_store_comp.delete_segment_stats_for_file",
        ) as mock_delete_segment_stats_for_file:
            result = delete_segment_stats_for_files(mock_db, [])

        assert result == 0
        mock_delete_segment_stats_for_file.assert_not_called()

    def test_returns_sum_of_deleted_counts_for_all_files(self) -> None:
        mock_db = MagicMock()
        file_ids = ["library_files/file-1", "library_files/file-2", "library_files/file-3"]

        with patch(
            "nomarr.components.ml.inference.ml_segment_stats_store_comp.delete_segment_stats_for_file",
            side_effect=[2, 0, 5],
        ) as mock_delete_segment_stats_for_file:
            result = delete_segment_stats_for_files(mock_db, file_ids)

        assert result == 7
        assert mock_delete_segment_stats_for_file.call_count == 3
        assert [call.args for call in mock_delete_segment_stats_for_file.call_args_list] == [
            (mock_db, "library_files/file-1"),
            (mock_db, "library_files/file-2"),
            (mock_db, "library_files/file-3"),
        ]
