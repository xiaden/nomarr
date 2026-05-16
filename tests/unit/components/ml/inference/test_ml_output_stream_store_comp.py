"""Tests for nomarr.components.ml.inference.ml_output_stream_store_comp module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.inference.ml_output_stream_store_comp import (
    LoadedOutputStream,
    StreamRecord,
    StreamWrite,
    build_output_stream_lookup,
    delete_output_streams,
    fetch_output_streams,
    load_output_streams_for_file,
    resolve_output_stream_lookup,
    upsert_output_streams,
)


@pytest.mark.unit
@pytest.mark.mocked
class TestUpsertOutputStreams:
    """Tests for ``upsert_output_streams``."""

    def test_returns_early_for_empty_streams(self) -> None:
        mock_db = MagicMock()

        upsert_output_streams(mock_db, file_id="library_files/file-1", streams=[])

        mock_db.ml.replace_output_streams_for_file.assert_not_called()

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

        mock_db.ml.replace_output_streams_for_file.assert_called_once_with(
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

        mock_db.ml.replace_output_streams_for_file.assert_called_once_with(
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
        mock_db.ml.list_output_streams_for_file.return_value = []

        result = fetch_output_streams(mock_db, "file-7")

        assert result == []
        mock_db.ml.list_output_streams_for_file.assert_called_once_with("library_files/file-7")

    def test_fetches_stream_records_sorted_by_output_index_then_id(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_output_streams_for_file.return_value = [
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
        mock_db.ml.list_output_streams_for_file.return_value = [
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
        mock_db.ml.list_output_streams_for_file.return_value = []

        result = delete_output_streams(mock_db, "file-9")

        assert result == 0
        mock_db.ml.list_output_streams_for_file.assert_called_once_with("library_files/file-9")
        mock_db.ml.replace_output_streams_for_file.assert_not_called()

    def test_deletes_stream_docs_for_file_once(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_output_streams_for_file.return_value = [
            {"_id": "ml_output_streams/stream-b"},
            {"_id": "ml_output_streams/stream-a"},
            {"_id": "ml_output_streams/stream-a"},
            {"values": [0.2]},
        ]

        result = delete_output_streams(mock_db, "library_files/file-4")

        assert result == 2
        mock_db.ml.replace_output_streams_for_file.assert_called_once_with("library_files/file-4", [])


@pytest.mark.unit
@pytest.mark.mocked
class TestBuildOutputStreamLookup:
    """Tests for ``build_output_stream_lookup``."""

    def test_returns_empty_dict_when_head_infos_is_empty(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.ml.inference.ml_output_stream_store_comp.build_model_output_index_map",
            return_value={},
        ) as mock_build_index_map:
            result = build_output_stream_lookup(mock_db, [])

        assert result == {}
        mock_build_index_map.assert_called_once_with(mock_db)

    def test_builds_lookup_from_head_infos_with_labels(self) -> None:
        mock_db = MagicMock()
        head_infos = [
            SimpleNamespace(name="mood", model_path="models/mood.onnx", labels=["sad", "happy"]),
            SimpleNamespace(name="genre", model_path="models/genre.onnx", labels=["rock"]),
        ]

        with patch(
            "nomarr.components.ml.inference.ml_output_stream_store_comp.build_model_output_index_map",
            return_value={
                "models/mood.onnx": {0: "ml_model_outputs/out-1", 1: "ml_model_outputs/out-2"},
                "models/genre.onnx": {0: "ml_model_outputs/out-3"},
            },
        ):
            result = build_output_stream_lookup(mock_db, head_infos)

        assert result == {
            "ml_model_outputs/out-1": ("mood", "sad"),
            "ml_model_outputs/out-2": ("mood", "happy"),
            "ml_model_outputs/out-3": ("genre", "rock"),
        }


@pytest.mark.unit
@pytest.mark.mocked
class TestResolveOutputStreamLookup:
    """Tests for ``resolve_output_stream_lookup``."""

    def test_returns_cached_lookup_unchanged_when_provided(self) -> None:
        mock_db = MagicMock()
        head_infos = [SimpleNamespace(name="mood", model_path="models/mood.onnx", labels=["happy"])]
        cached_lookup = {"ml_model_outputs/out-1": ("mood", "happy")}

        result = resolve_output_stream_lookup(mock_db, head_infos, cached_lookup=cached_lookup)

        assert result is cached_lookup

    def test_calls_build_output_stream_lookup_when_cache_missing(self) -> None:
        mock_db = MagicMock()
        head_infos = [SimpleNamespace(name="mood", model_path="models/mood.onnx", labels=["happy"])]
        expected_lookup = {"ml_model_outputs/out-1": ("mood", "happy")}

        with patch(
            "nomarr.components.ml.inference.ml_output_stream_store_comp.build_output_stream_lookup",
            return_value=expected_lookup,
        ) as mock_build_lookup:
            result = resolve_output_stream_lookup(mock_db, head_infos, cached_lookup=None)

        assert result == expected_lookup
        mock_build_lookup.assert_called_once_with(mock_db, head_infos)


@pytest.mark.unit
@pytest.mark.mocked
class TestLoadOutputStreamsForFile:
    """Tests for ``load_output_streams_for_file``."""

    def test_returns_empty_when_no_streams_are_found(self) -> None:
        mock_db = MagicMock()
        head_infos = [SimpleNamespace(name="mood", model_path="models/mood.onnx", labels=["happy"])]

        with (
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.fetch_output_streams",
                return_value=[],
            ) as mock_fetch,
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.resolve_output_stream_lookup"
            ) as mock_resolve,
        ):
            result = load_output_streams_for_file(
                mock_db,
                file_id="library_files/file-1",
                file_path="music/file-1.mp3",
                head_infos=head_infos,
            )

        assert result == []
        mock_fetch.assert_called_once_with(mock_db, "library_files/file-1")
        mock_resolve.assert_not_called()

    def test_returns_empty_when_streams_cannot_be_matched_to_lookup(self) -> None:
        mock_db = MagicMock()
        head_infos = [SimpleNamespace(name="mood", model_path="models/mood.onnx", labels=["happy"])]
        stream_records = [
            StreamRecord(
                output_id="ml_model_outputs/out-missing",
                output_index=0,
                values=[0.2, 0.8],
            )
        ]

        with (
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.fetch_output_streams",
                return_value=stream_records,
            ) as mock_fetch,
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.resolve_output_stream_lookup",
                return_value={"ml_model_outputs/out-1": ("mood", "happy")},
            ) as mock_resolve,
        ):
            result = load_output_streams_for_file(
                mock_db,
                file_id="library_files/file-2",
                file_path="music/file-2.mp3",
                head_infos=head_infos,
            )

        assert result == []
        mock_fetch.assert_called_once_with(mock_db, "library_files/file-2")
        mock_resolve.assert_called_once_with(mock_db, head_infos, cached_lookup=None)

    def test_returns_enriched_loaded_output_streams_when_all_streams_match(self) -> None:
        mock_db = MagicMock()
        head_infos = [
            SimpleNamespace(name="mood", model_path="models/mood.onnx", labels=["sad", "happy"]),
        ]
        stream_records = [
            StreamRecord(
                output_id="ml_model_outputs/out-1",
                output_index=0,
                values=[0.1, 0.9],
            ),
            StreamRecord(
                output_id="ml_model_outputs/out-2",
                output_index=1,
                values=[0.3, 0.7],
            ),
        ]

        with (
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.fetch_output_streams",
                return_value=stream_records,
            ) as mock_fetch,
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.resolve_output_stream_lookup",
                return_value={
                    "ml_model_outputs/out-1": ("mood", "sad"),
                    "ml_model_outputs/out-2": ("mood", "happy"),
                },
            ) as mock_resolve,
        ):
            result = load_output_streams_for_file(
                mock_db,
                file_id="library_files/file-3",
                file_path="music/file-3.mp3",
                head_infos=head_infos,
            )

        assert result == [
            LoadedOutputStream(
                head_name="mood",
                output_id="ml_model_outputs/out-1",
                output_index=0,
                label="sad",
                values=[0.1, 0.9],
            ),
            LoadedOutputStream(
                head_name="mood",
                output_id="ml_model_outputs/out-2",
                output_index=1,
                label="happy",
                values=[0.3, 0.7],
            ),
        ]
        mock_fetch.assert_called_once_with(mock_db, "library_files/file-3")
        mock_resolve.assert_called_once_with(mock_db, head_infos, cached_lookup=None)

    def test_passes_cached_output_lookup_to_resolver_when_provided(self) -> None:
        mock_db = MagicMock()
        head_infos = [SimpleNamespace(name="mood", model_path="models/mood.onnx", labels=["happy"])]
        cached_lookup = {"ml_model_outputs/out-1": ("mood", "happy")}
        stream_records = [
            StreamRecord(
                output_id="ml_model_outputs/out-1",
                output_index=0,
                values=[0.6],
            )
        ]

        with (
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.fetch_output_streams",
                return_value=stream_records,
            ) as mock_fetch,
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.resolve_output_stream_lookup",
                return_value=cached_lookup,
            ) as mock_resolve,
        ):
            result = load_output_streams_for_file(
                mock_db,
                file_id="library_files/file-4",
                file_path="music/file-4.mp3",
                head_infos=head_infos,
                output_lookup=cached_lookup,
            )

        assert result == [
            LoadedOutputStream(
                head_name="mood",
                output_id="ml_model_outputs/out-1",
                output_index=0,
                label="happy",
                values=[0.6],
            )
        ]
        mock_fetch.assert_called_once_with(mock_db, "library_files/file-4")
        mock_resolve.assert_called_once_with(mock_db, head_infos, cached_lookup=cached_lookup)
