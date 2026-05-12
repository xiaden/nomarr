"""Tests for nomarr.components.ml.inference.ml_output_stream_store_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.inference.ml_output_stream_store_comp import (
    StreamRecord,
    StreamWrite,
    delete_output_streams,
    fetch_output_streams,
    upsert_output_streams,
)


@pytest.mark.unit
@pytest.mark.mocked
class TestUpsertOutputStreams:
    """Tests for ``upsert_output_streams``."""

    def test_returns_early_for_empty_streams(self) -> None:
        mock_db = MagicMock()

        upsert_output_streams(mock_db, file_id="library_files/file-1", streams=[])

        mock_db.ml.upsert_output_streams_batch.assert_not_called()

    def test_upserts_normalized_stream_payloads(self) -> None:
        mock_db = MagicMock()
        file_id = "file-1"
        output_1 = "out-1"
        output_2 = "ml_model_outputs/out-2"

        upsert_output_streams(
            mock_db,
            file_id=file_id,
            streams=[
                StreamWrite(output_id=output_1, values=[0.1, 0.2]),
                StreamWrite(output_id=output_2, values=[0.3, 0.4]),
            ],
        )

        mock_db.ml.upsert_output_streams_batch.assert_called_once_with(
            file_id="library_files/file-1",
            stream_payloads=[
                {"output_id": "ml_model_outputs/out-1", "values": [0.1, 0.2]},
                {"output_id": "ml_model_outputs/out-2", "values": [0.3, 0.4]},
            ],
        )

    def test_last_stream_for_output_wins_within_batch(self) -> None:
        mock_db = MagicMock()

        upsert_output_streams(
            mock_db,
            file_id="library_files/file-1",
            streams=[
                StreamWrite(output_id="out-1", values=[0.1]),
                StreamWrite(output_id="ml_model_outputs/out-1", values=[0.9, 1.1]),
            ],
        )

        mock_db.ml.upsert_output_streams_batch.assert_called_once_with(
            file_id="library_files/file-1",
            stream_payloads=[
                {"output_id": "ml_model_outputs/out-1", "values": [0.9, 1.1]},
            ],
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestFetchOutputStreams:
    """Tests for ``fetch_output_streams``."""

    def test_returns_empty_when_file_has_no_streams(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_output_streams_for_file.return_value = []

        result = fetch_output_streams(mock_db, "file-7")

        assert result == []
        mock_db.ml.get_output_streams_for_file.assert_called_once_with("library_files/file-7")

    def test_fetches_stream_records_sorted_by_output_index_then_id(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_output_streams_for_file.return_value = [
            {
                "_id": "ml_output_streams/stream-b",
                "output_id": "ml_model_outputs/out-b",
                "output_index": 2,
                "values": [1, 2],
            },
            {
                "_id": "ml_output_streams/stream-a",
                "output_id": "ml_model_outputs/out-a",
                "output_index": 1,
                "values": [3.5, 4.5],
            },
            {"_id": None, "output_id": "ml_model_outputs/out-z", "output_index": 9, "values": [9.9]},
            {
                "_id": "ml_output_streams/stream-c",
                "output_id": "ml_model_outputs/out-c",
                "output_index": 3,
                "values": "bad",
            },
        ]

        result = fetch_output_streams(mock_db, "library_files/file-2")

        assert result == [
            StreamRecord(output_id="ml_model_outputs/out-a", output_index=1, values=[3.5, 4.5]),
            StreamRecord(output_id="ml_model_outputs/out-b", output_index=2, values=[1.0, 2.0]),
            StreamRecord(output_id="ml_model_outputs/out-z", output_index=9, values=[9.9]),
        ]

    def test_skips_streams_without_valid_output_metadata(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_output_streams_for_file.return_value = [
            {"_id": "ml_output_streams/stream-1", "values": [0.1]},
            {"_id": "ml_output_streams/stream-2", "output_id": None, "output_index": 0, "values": [0.2]},
            {
                "_id": "ml_output_streams/stream-3",
                "output_id": "ml_model_outputs/out-3",
                "output_index": "bad",
                "values": [0.3],
            },
        ]

        result = fetch_output_streams(mock_db, "library_files/file-3")

        assert result == []


@pytest.mark.unit
@pytest.mark.mocked
class TestDeleteOutputStreams:
    """Tests for ``delete_output_streams``."""

    def test_returns_zero_when_file_has_no_streams(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_output_streams_for_file.return_value = []

        result = delete_output_streams(mock_db, "file-9")

        assert result == 0
        mock_db.ml.get_output_streams_for_file.assert_called_once_with("library_files/file-9")
        mock_db.ml.delete_output_streams_for_file.assert_not_called()

    def test_deletes_stream_docs_for_file_once(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.get_output_streams_for_file.return_value = [
            {"_id": "ml_output_streams/stream-b"},
            {"_id": "ml_output_streams/stream-a"},
            {"_id": "ml_output_streams/stream-a"},
            {"values": [0.2]},
        ]

        result = delete_output_streams(mock_db, "library_files/file-4")

        assert result == 2
        mock_db.ml.delete_output_streams_for_file.assert_called_once_with("library_files/file-4")
