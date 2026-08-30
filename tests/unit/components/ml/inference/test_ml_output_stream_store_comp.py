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
    build_output_stream_payloads,
    delete_output_streams,
    fetch_output_streams,
    load_output_streams_for_song,
    resolve_output_stream_lookup,
)
from nomarr.helpers.dataclasses.ml_output_stream_dataclass import OutputStream, OutputStreamWrite


@pytest.mark.unit
@pytest.mark.mocked
class TestBuildOutputStreamPayloads:
    """Tests for ``build_output_stream_payloads`` (canonical aggregate payloads)."""

    def test_returns_empty_list_for_empty_streams(self) -> None:
        assert build_output_stream_payloads([]) == []

    def test_builds_canonical_normalized_payloads(self) -> None:
        result = build_output_stream_payloads(
            [
                StreamWrite(output_id="out-1", values=[0.1, 0.2]),
                StreamWrite(output_id="ml_model_outputs/out-2", values=[0.3, 0.4]),
            ]
        )

        assert result == [
            OutputStreamWrite(output_id="out-1", values=[0.1, 0.2]),
            OutputStreamWrite(output_id="ml_model_outputs/out-2", values=[0.3, 0.4]),
        ]

    def test_last_stream_for_output_wins_within_batch(self) -> None:
        result = build_output_stream_payloads(
            [
                StreamWrite(output_id="out-1", values=[0.1]),
                StreamWrite(output_id="ml_model_outputs/out-1", values=[0.9, 1.1]),
            ]
        )

        assert result == [
            OutputStreamWrite(output_id="out-1", values=[0.1]),
            OutputStreamWrite(output_id="ml_model_outputs/out-1", values=[0.9, 1.1]),
        ]

    def test_duplicate_output_id_normalized_last_wins(self) -> None:
        result = build_output_stream_payloads(
            [
                StreamWrite(output_id="head_0", values=[0.1, 0.9]),
                StreamWrite(output_id="head_0", values=[0.4, 0.6]),
            ]
        )

        assert result == [OutputStreamWrite(output_id="head_0", values=[0.4, 0.6])]

    def test_live_shape_payload_carries_output_index(self) -> None:
        """The live write shape threads ``output_index`` through the payload."""
        result = build_output_stream_payloads(
            [
                StreamWrite(output_id="ml_model_outputs/out-0", values=[0.1, 0.9], output_index=0),
                StreamWrite(output_id="ml_model_outputs/out-1", values=[0.3, 0.7], output_index=1),
            ]
        )

        assert result == [
            OutputStreamWrite(output_id="ml_model_outputs/out-0", values=[0.1, 0.9], output_index=0),
            OutputStreamWrite(output_id="ml_model_outputs/out-1", values=[0.3, 0.7], output_index=1),
        ]


@pytest.mark.unit
@pytest.mark.mocked
class TestFetchOutputStreams:
    """Tests for ``fetch_output_streams``."""

    def test_returns_empty_when_file_has_no_streams(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_output_streams_for_song.return_value = []

        result = fetch_output_streams(mock_db, song_id=7)

        assert result == []
        mock_db.ml.list_output_streams_for_song.assert_called_once_with(7)

    def test_fetches_stream_records_sorted_by_output_index_then_id(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.list_output_streams_for_song.return_value = [
            OutputStream(output_id="ml_model_outputs/out-b", output_index=2, values=[1, 2]),
            OutputStream(output_id="ml_model_outputs/out-a", output_index=1, values=[3.5, 4.5]),
            OutputStream(output_id="ml_model_outputs/out-z", output_index=9, values=[9.9]),
        ]

        result = fetch_output_streams(mock_db, song_id=f"{'songs'}/file-2")

        assert result == [
            StreamRecord(output_id="ml_model_outputs/out-a", output_index=1, values=[3.5, 4.5]),
            StreamRecord(output_id="ml_model_outputs/out-b", output_index=2, values=[1.0, 2.0]),
            StreamRecord(output_id="ml_model_outputs/out-z", output_index=9, values=[9.9]),
        ]

    def test_skips_streams_without_valid_output_metadata(self) -> None:
        mock_db = MagicMock()
        # Invalid storage rows are rejected by the persistence facade before
        # this component is called; this test exercises the empty domain result.
        mock_db.ml.list_output_streams_for_song.return_value = []

        result = fetch_output_streams(mock_db, song_id=f"{'songs'}/file-3")

        assert result == []

    def test_live_shape_write_to_fetch_round_trip_carries_output_index(self) -> None:
        """A live write-read round-trip survives with its output_index intact.

        Reproduces the exact deferred/live shape: the canonical payload the
        aggregate persists (with output_index) is what the facade read
        returns, and fetch_output_streams must surface the index rather than
        dropping the row (which previously forced a re-inference loop).
        """
        mock_db = MagicMock()
        # The write side: payloads built from the live shape carry the index.
        payloads = build_output_stream_payloads(
            [
                StreamWrite(output_id="ml_model_outputs/out-0", values=[0.1, 0.9], output_index=0),
                StreamWrite(output_id="ml_model_outputs/out-1", values=[0.3, 0.7], output_index=1),
            ]
        )
        assert payloads == [
            StreamWrite(output_id="ml_model_outputs/out-0", values=[0.1, 0.9], output_index=0),
            StreamWrite(output_id="ml_model_outputs/out-1", values=[0.3, 0.7], output_index=1),
        ]

        # The read side: the persisted rows (as the facade returns them) must
        # round-trip the index through fetch_output_streams.
        mock_db.ml.list_output_streams_for_song.return_value = [
            StreamRecord(
                output_id=payload.output_id,
                values=payload.values,
                output_index=payload.output_index,
            )
            for payload in payloads
        ]
        records = fetch_output_streams(mock_db, song_id=7)

        assert records == [
            StreamRecord(output_id="ml_model_outputs/out-0", output_index=0, values=[0.1, 0.9]),
            StreamRecord(output_id="ml_model_outputs/out-1", output_index=1, values=[0.3, 0.7]),
        ]

    def test_fetch_places_legacy_none_output_index_after_indexed_rows(self) -> None:
        """Legacy output_index=None streams remain valid domain objects."""
        mock_db = MagicMock()
        mock_db.ml.list_output_streams_for_song.return_value = [
            OutputStream(output_id="ml_model_outputs/out-null", output_index=None, values=[0.1]),
            OutputStream(output_id="ml_model_outputs/out-ok", output_index=1, values=[0.5]),
        ]

        result = fetch_output_streams(mock_db, song_id=7)

        assert result == [
            StreamRecord(output_id="ml_model_outputs/out-ok", output_index=1, values=[0.5]),
            StreamRecord(output_id="ml_model_outputs/out-null", output_index=None, values=[0.1]),
        ]


@pytest.mark.unit
@pytest.mark.mocked
class TestDeleteOutputStreams:
    """Tests for ``delete_output_streams``."""

    def test_returns_facade_deletion_count_when_file_has_no_streams(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.remove_output_streams_for_song.return_value = 0

        result = delete_output_streams(mock_db, song_id=9)

        assert result == 0
        mock_db.ml.list_output_streams_for_song.assert_not_called()
        mock_db.ml.remove_output_streams_for_song.assert_called_once_with(9)

    def test_returns_facade_deletion_count_without_reading_storage_rows(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.remove_output_streams_for_song.return_value = 2

        result = delete_output_streams(mock_db, song_id=4)

        assert result == 2
        mock_db.ml.list_output_streams_for_song.assert_not_called()
        mock_db.ml.remove_output_streams_for_song.assert_called_once_with(4)


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
class TestLoadOutputStreamsForSong:
    """Tests for ``load_output_streams_for_song``."""

    def test_returns_empty_when_no_streams_are_found(self) -> None:
        mock_db = MagicMock()
        head_infos = [SimpleNamespace(name="mood", model_path="models/mood.onnx", labels=["happy"])]

        with (
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.fetch_output_streams",
                return_value=[],
            ) as mock_fetch,
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.transition_song_state"
            ) as mock_transition,
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.resolve_output_stream_lookup"
            ) as mock_resolve,
        ):
            result = load_output_streams_for_song(
                mock_db,
                song_id=f"{'songs'}/file-1",
                file_path="music/file-1.mp3",
                head_infos=head_infos,
            )

        assert result == []
        mock_fetch.assert_called_once_with(mock_db, f"{'songs'}/file-1")
        mock_transition.assert_called_once_with(
            mock_db,
            [f"{'songs'}/file-1"],
            "processed",
            "not_processed",
        )
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
                "nomarr.components.ml.inference.ml_output_stream_store_comp.transition_song_state"
            ) as mock_transition,
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.resolve_output_stream_lookup",
                return_value={"ml_model_outputs/out-1": ("mood", "happy")},
            ) as mock_resolve,
        ):
            result = load_output_streams_for_song(
                mock_db,
                song_id=f"{'songs'}/file-2",
                file_path="music/file-2.mp3",
                head_infos=head_infos,
            )

        assert result == []
        mock_fetch.assert_called_once_with(mock_db, f"{'songs'}/file-2")
        mock_transition.assert_called_once_with(
            mock_db,
            [f"{'songs'}/file-2"],
            "processed",
            "not_processed",
        )
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
            result = load_output_streams_for_song(
                mock_db,
                song_id=f"{'songs'}/file-3",
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
        mock_fetch.assert_called_once_with(mock_db, f"{'songs'}/file-3")
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
            result = load_output_streams_for_song(
                mock_db,
                song_id=f"{'songs'}/file-4",
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
        mock_fetch.assert_called_once_with(mock_db, f"{'songs'}/file-4")
        mock_resolve.assert_called_once_with(mock_db, head_infos, cached_lookup=cached_lookup)
