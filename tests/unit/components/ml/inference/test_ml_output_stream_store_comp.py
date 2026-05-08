"""Tests for nomarr.components.ml.inference.ml_output_stream_store_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.inference.ml_output_stream_store_comp import (
    StreamRecord,
    StreamWrite,
    _file_stream_edge_key,
    _output_stream_edge_key,
    _stream_key,
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

        mock_db.ml_output_streams.upsert_batch.assert_not_called()
        mock_db.file_has_output_stream.upsert_batch.assert_not_called()
        mock_db.output_has_stream.upsert_batch.assert_not_called()

    def test_upserts_docs_and_edges_with_deterministic_keys(self) -> None:
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

        normalized_file_id = "library_files/file-1"
        normalized_output_1 = "ml_model_outputs/out-1"
        stream_key_1 = _stream_key(normalized_file_id, normalized_output_1)
        stream_key_2 = _stream_key(normalized_file_id, output_2)
        stream_id_1 = f"ml_output_streams/{stream_key_1}"
        stream_id_2 = f"ml_output_streams/{stream_key_2}"

        mock_db.ml_output_streams.upsert_batch.assert_called_once_with(
            [
                {"_key": stream_key_1, "values": [0.1, 0.2]},
                {"_key": stream_key_2, "values": [0.3, 0.4]},
            ],
            match_fields="_key",
        )
        mock_db.file_has_output_stream.upsert_batch.assert_called_once_with(
            [
                {
                    "_key": _file_stream_edge_key(normalized_file_id, stream_id_1),
                    "_from": normalized_file_id,
                    "_to": stream_id_1,
                },
                {
                    "_key": _file_stream_edge_key(normalized_file_id, stream_id_2),
                    "_from": normalized_file_id,
                    "_to": stream_id_2,
                },
            ],
            match_fields=["_from", "_to"],
        )
        mock_db.output_has_stream.upsert_batch.assert_called_once_with(
            [
                {
                    "_key": _output_stream_edge_key(normalized_output_1, stream_id_1),
                    "_from": normalized_output_1,
                    "_to": stream_id_1,
                },
                {
                    "_key": _output_stream_edge_key(output_2, stream_id_2),
                    "_from": output_2,
                    "_to": stream_id_2,
                },
            ],
            match_fields=["_from", "_to"],
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

        mock_db.ml_output_streams.upsert_batch.assert_called_once_with(
            [
                {
                    "_key": _stream_key("library_files/file-1", "ml_model_outputs/out-1"),
                    "values": [0.9, 1.1],
                }
            ],
            match_fields="_key",
        )
        mock_db.file_has_output_stream.upsert_batch.assert_called_once()
        mock_db.output_has_stream.upsert_batch.assert_called_once()


@pytest.mark.unit
@pytest.mark.mocked
class TestFetchOutputStreams:
    """Tests for ``fetch_output_streams``."""

    def test_returns_empty_when_file_has_no_streams(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.file_has_output_stream.return_value = []

        result = fetch_output_streams(mock_db, "file-7")

        assert result == []
        mock_db.library_files.file_has_output_stream.assert_called_once_with("library_files/file-7", limit=None)
        mock_db.ml_output_streams.output_has_stream.assert_not_called()

    def test_fetches_stream_records_sorted_by_output_index_then_id(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.file_has_output_stream.return_value = [
            {"_id": "ml_output_streams/stream-b", "values": [1, 2]},
            {"_id": "ml_output_streams/stream-a", "values": [3.5, 4.5]},
            {"_id": None, "values": [9.9]},
            {"_id": "ml_output_streams/stream-c", "values": "bad"},
        ]
        mock_db.ml_output_streams.output_has_stream.side_effect = [
            [{"_id": "ml_model_outputs/out-b", "output_index": 2}],
            [{"_id": "ml_model_outputs/out-a", "output_index": 1}],
        ]

        result = fetch_output_streams(mock_db, "library_files/file-2")

        assert result == [
            StreamRecord(output_id="ml_model_outputs/out-a", output_index=1, values=[3.5, 4.5]),
            StreamRecord(output_id="ml_model_outputs/out-b", output_index=2, values=[1.0, 2.0]),
        ]
        assert mock_db.ml_output_streams.output_has_stream.call_count == 2
        mock_db.ml_output_streams.output_has_stream.assert_any_call("ml_output_streams/stream-b", limit=1)
        mock_db.ml_output_streams.output_has_stream.assert_any_call("ml_output_streams/stream-a", limit=1)

    def test_skips_streams_without_valid_output_metadata(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.file_has_output_stream.return_value = [
            {"_id": "ml_output_streams/stream-1", "values": [0.1]},
            {"_id": "ml_output_streams/stream-2", "values": [0.2]},
            {"_id": "ml_output_streams/stream-3", "values": [0.3]},
        ]
        mock_db.ml_output_streams.output_has_stream.side_effect = [
            [],
            [{"_id": None, "output_index": 0}],
            [{"_id": "ml_model_outputs/out-3", "output_index": "bad"}],
        ]

        result = fetch_output_streams(mock_db, "library_files/file-3")

        assert result == []


@pytest.mark.unit
@pytest.mark.mocked
class TestDeleteOutputStreams:
    """Tests for ``delete_output_streams``."""

    def test_returns_zero_when_file_has_no_streams(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.file_has_output_stream.return_value = []

        result = delete_output_streams(mock_db, "file-9")

        assert result == 0
        mock_db.library_files.file_has_output_stream.assert_called_once_with("library_files/file-9", limit=None)
        mock_db.file_has_output_stream._to.delete.in_.assert_not_called()
        mock_db.output_has_stream._to.delete.in_.assert_not_called()
        mock_db.ml_output_streams._id.delete.in_.assert_not_called()

    def test_deletes_file_edges_output_edges_and_stream_docs_once(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.file_has_output_stream.return_value = [
            {"_id": "ml_output_streams/stream-b"},
            {"_id": "ml_output_streams/stream-a"},
            {"_id": "ml_output_streams/stream-a"},
            {"values": [0.2]},
        ]
        mock_db.ml_output_streams._id.delete.in_.return_value = 2

        result = delete_output_streams(mock_db, "library_files/file-4")

        assert result == 2
        expected_stream_ids = ["ml_output_streams/stream-a", "ml_output_streams/stream-b"]
        mock_db.file_has_output_stream._to.delete.in_.assert_called_once_with(expected_stream_ids)
        mock_db.output_has_stream._to.delete.in_.assert_called_once_with(expected_stream_ids)
        mock_db.ml_output_streams._id.delete.in_.assert_called_once_with(expected_stream_ids)
