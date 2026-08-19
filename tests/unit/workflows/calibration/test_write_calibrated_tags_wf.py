"""Tests for canonical-stream calibrated-tags workflow helpers."""

from __future__ import annotations

import importlib
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.helpers.dto.calibration_dto import WriteCalibratedTagsParams
from nomarr.helpers.dto.ml_dto import HeadOutput, LoadedOutputStream

stream_store_module = importlib.import_module("nomarr.components.ml.inference.ml_output_stream_store_comp")
wf_module = importlib.import_module("nomarr.workflows.calibration.write_calibrated_tags_wf")
StreamRecord = stream_store_module.StreamRecord


def _make_tags(**items: str) -> Tags:
    """Create a Tags DTO from scalar string values."""
    return Tags(items=tuple(Tag(name=key, values=(value,)) for key, value in items.items()))


class _FakeHeadInfo:
    def __init__(self, *, name: str, labels: list[str], model_path: str, is_regression_head: bool = False) -> None:
        self.name = name
        self.labels = labels
        self.model_path = model_path
        self.is_regression_head = is_regression_head


@pytest.mark.unit
@pytest.mark.mocked
class TestLoadOutputStreamsForFile:
    """Tests for canonical stream loading and enrichment."""

    def test_enriches_fetched_streams_with_head_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = MagicMock()
        head_infos = [_FakeHeadInfo(name="mood_multiclass", labels=["happy", "sad"], model_path="/models/mood.onnx")]
        fetch_output_streams = MagicMock(
            return_value=[
                StreamRecord(output_id="ml_model_outputs/out-1", output_index=0, values=[0.8, 0.7]),
                StreamRecord(output_id="ml_model_outputs/out-2", output_index=1, values=[0.2, 0.3]),
            ]
        )
        monkeypatch.setattr(stream_store_module, "fetch_output_streams", fetch_output_streams)

        result = stream_store_module.load_output_streams_for_song(
            db,
            f"{'songs'}/1",
            "/music/example.flac",
            head_infos,
            output_lookup={
                "ml_model_outputs/out-1": ("mood_multiclass", "happy"),
                "ml_model_outputs/out-2": ("mood_multiclass", "sad"),
            },
        )

        assert result == [
            LoadedOutputStream(
                head_name="mood_multiclass",
                output_id="ml_model_outputs/out-1",
                output_index=0,
                label="happy",
                values=[0.8, 0.7],
            ),
            LoadedOutputStream(
                head_name="mood_multiclass",
                output_id="ml_model_outputs/out-2",
                output_index=1,
                label="sad",
                values=[0.2, 0.3],
            ),
        ]
        fetch_output_streams.assert_called_once_with(db, f"{'songs'}/1")

    def test_returns_empty_and_skips_lookup_when_streams_are_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = MagicMock()
        db.app.get_song_states_for_songs = MagicMock(return_value={})
        db.app.remove_song_states = MagicMock()
        db.app.add_song_states = MagicMock()
        head_infos = [_FakeHeadInfo(name="mood_multiclass", labels=["happy", "sad"], model_path="/models/mood.onnx")]
        fetch_output_streams = MagicMock(return_value=[])
        monkeypatch.setattr(stream_store_module, "fetch_output_streams", fetch_output_streams)

        result = stream_store_module.load_output_streams_for_song(
            db,
            f"{'songs'}/1",
            "/music/example.flac",
            head_infos,
            output_lookup={"ml_model_outputs/out-1": ("mood_multiclass", "happy")},
        )

        assert result == []

    def test_returns_empty_when_any_stream_cannot_be_matched_to_discovered_heads(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = MagicMock()
        db.app.get_song_states_for_songs = MagicMock(return_value={})
        db.app.remove_song_states = MagicMock()
        db.app.add_song_states = MagicMock()
        head_infos = [_FakeHeadInfo(name="mood_multiclass", labels=["happy", "sad"], model_path="/models/mood.onnx")]
        monkeypatch.setattr(
            stream_store_module,
            "fetch_output_streams",
            MagicMock(return_value=[StreamRecord(output_id="ml_model_outputs/out-404", output_index=0, values=[0.5])]),
        )

        result = stream_store_module.load_output_streams_for_song(
            db,
            f"{'songs'}/1",
            "/music/example.flac",
            head_infos,
            output_lookup={"ml_model_outputs/out-1": ("mood_multiclass", "happy")},
        )

        assert result == []


@pytest.mark.unit
@pytest.mark.mocked
class TestWriteCalibratedTagsWorkflow:
    """Tests for stream-based calibration writes."""

    def test_uses_canonical_streams_and_never_touches_legacy_segment_stats(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = MagicMock()
        params = WriteCalibratedTagsParams(
            file_path="/music/example.flac",
            models_dir="/models",
            namespace="nom",
            version_tag_key="version",
            calibrate_heads=False,
        )
        head_infos = [_FakeHeadInfo(name="mood_multiclass", labels=["happy", "sad"], model_path="/models/mood.onnx")]
        output_streams = [
            LoadedOutputStream(
                head_name="mood_multiclass",
                output_id="ml_model_outputs/out-1",
                output_index=0,
                label="happy",
                values=[0.8, 0.7],
            )
        ]
        head_outputs = [
            HeadOutput(
                head=cast("Any", head_infos[0]),
                model_key="model:mood_multiclass:happy:none:0",
                label="happy",
                value=0.8,
                tier="high",
                calibration_id=None,
            )
        ]
        mood_tags = _make_tags(**{"nom:mood-happy": "high"})
        require_library_song_id = MagicMock(return_value=f"{'songs'}/1")
        discover_heads = MagicMock(return_value=head_infos)
        build_output_stream_lookup = MagicMock(return_value={"ml_model_outputs/out-1": ("mood_multiclass", "happy")})
        load_output_streams_for_song = MagicMock(return_value=output_streams)
        reconstruct = MagicMock(return_value=head_outputs)
        aggregate_mood_tags = MagicMock(return_value=mood_tags)
        save_mood_tags = MagicMock()
        get_calibration_version = MagicMock(return_value="cal-v1")
        update_file_calibration_hash = MagicMock()
        monkeypatch.setattr(wf_module, "require_library_song_id", require_library_song_id)
        monkeypatch.setattr(wf_module, "discover_heads", discover_heads)
        monkeypatch.setattr(wf_module, "build_output_stream_lookup", build_output_stream_lookup)
        monkeypatch.setattr(wf_module, "load_output_streams_for_song", load_output_streams_for_song)
        monkeypatch.setattr(wf_module, "reconstruct_head_outputs_from_streams", reconstruct)
        monkeypatch.setattr(wf_module, "aggregate_mood_tags", aggregate_mood_tags)
        monkeypatch.setattr(wf_module, "save_mood_tags", save_mood_tags)
        monkeypatch.setattr(wf_module, "get_calibration_version", get_calibration_version)
        monkeypatch.setattr(wf_module, "update_file_calibration_hash", update_file_calibration_hash)
        monkeypatch.setattr(wf_module, "load_calibration_lookup", MagicMock(return_value={"happy": {"p5": 0.1}}))

        assert wf_module.write_calibrated_tags_wf(db, params) is True

        require_library_song_id.assert_called_once_with(db, "/music/example.flac")
        build_output_stream_lookup.assert_called_once_with(db, head_infos)
        load_output_streams_for_song.assert_called_once_with(
            db,
            f"{'songs'}/1",
            "/music/example.flac",
            head_infos,
            output_lookup={"ml_model_outputs/out-1": ("mood_multiclass", "happy")},
        )
        reconstruct.assert_called_once_with(
            output_streams=output_streams,
            head_infos=head_infos,
            calibrations={"happy": {"p5": 0.1}},
        )
        aggregate_mood_tags.assert_called_once_with(head_outputs)
        save_mood_tags.assert_called_once_with(db, f"{'songs'}/1", mood_tags)
        update_file_calibration_hash.assert_called_once_with(db, f"{'songs'}/1")
        assert db.segment_scores_stats.mock_calls == []

    def test_none_aggregation_still_writes_none_tiers_and_marks_hash(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When aggregation produces no mood tags, None is still written to clear stale tiers."""
        db = MagicMock()
        params = WriteCalibratedTagsParams(
            file_path="/music/example.flac",
            models_dir="/models",
            namespace="nom",
            version_tag_key="version",
            calibrate_heads=False,
        )
        head_infos = [_FakeHeadInfo(name="mood_multiclass", labels=["happy", "sad"], model_path="/models/mood.onnx")]
        output_streams = [
            LoadedOutputStream(
                head_name="mood_multiclass",
                output_id="ml_model_outputs/out-1",
                output_index=0,
                label="happy",
                values=[0.8, 0.7],
            )
        ]
        head_outputs = [
            HeadOutput(
                head=cast("Any", head_infos[0]),
                model_key="model:mood_multiclass:happy:none:0",
                label="happy",
                value=0.8,
                tier="high",
                calibration_id=None,
            )
        ]
        require_library_song_id = MagicMock(return_value=f"{'songs'}/1")
        discover_heads = MagicMock(return_value=head_infos)
        build_output_stream_lookup = MagicMock(return_value={"ml_model_outputs/out-1": ("mood_multiclass", "happy")})
        load_output_streams_for_song = MagicMock(return_value=output_streams)
        reconstruct = MagicMock(return_value=head_outputs)
        aggregate_mood_tags = MagicMock(return_value=None)
        save_mood_tags = MagicMock()
        get_calibration_version = MagicMock(return_value="cal-v1")
        update_file_calibration_hash = MagicMock()
        monkeypatch.setattr(wf_module, "require_library_song_id", require_library_song_id)
        monkeypatch.setattr(wf_module, "discover_heads", discover_heads)
        monkeypatch.setattr(wf_module, "build_output_stream_lookup", build_output_stream_lookup)
        monkeypatch.setattr(wf_module, "load_output_streams_for_song", load_output_streams_for_song)
        monkeypatch.setattr(wf_module, "reconstruct_head_outputs_from_streams", reconstruct)
        monkeypatch.setattr(wf_module, "aggregate_mood_tags", aggregate_mood_tags)
        monkeypatch.setattr(wf_module, "save_mood_tags", save_mood_tags)
        monkeypatch.setattr(wf_module, "get_calibration_version", get_calibration_version)
        monkeypatch.setattr(wf_module, "update_file_calibration_hash", update_file_calibration_hash)
        monkeypatch.setattr(wf_module, "load_calibration_lookup", MagicMock(return_value={}))

        assert wf_module.write_calibrated_tags_wf(db, params) is True

        save_mood_tags.assert_called_once_with(db, f"{'songs'}/1", None)
        update_file_calibration_hash.assert_called_once_with(db, f"{'songs'}/1")

    def test_batch_context_reuses_cached_output_lookup_and_defers_batch_writes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = MagicMock()
        params_1 = WriteCalibratedTagsParams(
            file_path="/music/example-1.flac",
            models_dir="/models",
            namespace="nom",
            version_tag_key="version",
            calibrate_heads=False,
        )
        params_2 = WriteCalibratedTagsParams(
            file_path="/music/example-2.flac",
            models_dir="/models",
            namespace="nom",
            version_tag_key="version",
            calibrate_heads=False,
        )
        head_infos = [_FakeHeadInfo(name="mood_multiclass", labels=["happy", "sad"], model_path="/models/mood.onnx")]
        lookup = {"ml_model_outputs/out-1": ("mood_multiclass", "happy")}
        output_streams_1 = [
            LoadedOutputStream(
                head_name="mood_multiclass",
                output_id="ml_model_outputs/out-1",
                output_index=0,
                label="happy",
                values=[0.8, 0.7],
            )
        ]
        output_streams_2 = [
            LoadedOutputStream(
                head_name="mood_multiclass",
                output_id="ml_model_outputs/out-1",
                output_index=0,
                label="happy",
                values=[0.6, 0.5],
            )
        ]
        head_outputs_1 = [
            HeadOutput(
                head=cast("Any", head_infos[0]),
                model_key="model:mood_multiclass:happy:none:0",
                label="happy",
                value=0.8,
                tier="high",
                calibration_id=None,
            )
        ]
        head_outputs_2 = [
            HeadOutput(
                head=cast("Any", head_infos[0]),
                model_key="model:mood_multiclass:happy:none:0",
                label="happy",
                value=0.6,
                tier="medium",
                calibration_id=None,
            )
        ]
        mood_tags_1 = _make_tags(**{"nom:mood-happy": "high"})
        mood_tags_2 = _make_tags(**{"nom:mood-happy": "medium"})
        batch_ctx = wf_module.BatchContext(
            heads=head_infos,
            calibrations={"happy": {"p5": 0.1}},
            calibration_version="cal-v1",
        )
        require_library_song_id = MagicMock(side_effect=[f"{'songs'}/1", f"{'songs'}/2"])
        discover_heads = MagicMock()
        build_output_stream_lookup = MagicMock(return_value=lookup)
        load_output_streams_for_song = MagicMock(side_effect=[output_streams_1, output_streams_2])
        reconstruct = MagicMock(side_effect=[head_outputs_1, head_outputs_2])
        aggregate_mood_tags = MagicMock(side_effect=[mood_tags_1, mood_tags_2])
        save_mood_tags = MagicMock()
        update_file_calibration_hash = MagicMock()
        monkeypatch.setattr(wf_module, "require_library_song_id", require_library_song_id)
        monkeypatch.setattr(wf_module, "discover_heads", discover_heads)
        monkeypatch.setattr(wf_module, "build_output_stream_lookup", build_output_stream_lookup)
        monkeypatch.setattr(wf_module, "load_output_streams_for_song", load_output_streams_for_song)
        monkeypatch.setattr(wf_module, "reconstruct_head_outputs_from_streams", reconstruct)
        monkeypatch.setattr(wf_module, "aggregate_mood_tags", aggregate_mood_tags)
        monkeypatch.setattr(wf_module, "save_mood_tags", save_mood_tags)
        monkeypatch.setattr(wf_module, "update_file_calibration_hash", update_file_calibration_hash)

        wf_module.write_calibrated_tags_wf(db, params_1, batch_ctx=batch_ctx)
        wf_module.write_calibrated_tags_wf(db, params_2, batch_ctx=batch_ctx)

        discover_heads.assert_not_called()
        build_output_stream_lookup.assert_called_once_with(db, head_infos)
        assert batch_ctx.output_stream_lookup is lookup
        assert load_output_streams_for_song.call_count == 2
        assert load_output_streams_for_song.call_args_list[0].kwargs["output_lookup"] is lookup
        assert load_output_streams_for_song.call_args_list[1].kwargs["output_lookup"] is lookup
        assert batch_ctx.pending_mood_tags == [
            (f"{'songs'}/1", mood_tags_1),
            (f"{'songs'}/2", mood_tags_2),
        ]
        assert batch_ctx.pending_calibration_hashes == [
            f"{'songs'}/1",
            f"{'songs'}/2",
        ]
        save_mood_tags.assert_not_called()
        update_file_calibration_hash.assert_not_called()

    def test_returns_early_when_streams_are_missing_and_leaves_db_untouched(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db = MagicMock()
        params = WriteCalibratedTagsParams(
            file_path="/music/example.flac",
            models_dir="/models",
            namespace="nom",
            version_tag_key="version",
            calibrate_heads=False,
        )
        head_infos = [_FakeHeadInfo(name="mood_multiclass", labels=["happy", "sad"], model_path="/models/mood.onnx")]
        require_library_song_id = MagicMock(return_value=f"{'songs'}/1")
        discover_heads = MagicMock(return_value=head_infos)
        build_output_stream_lookup = MagicMock(return_value={"ml_model_outputs/out-1": ("mood_multiclass", "happy")})
        load_output_streams_for_song = MagicMock(return_value=[])
        reconstruct = MagicMock()
        save_mood_tags = MagicMock()
        update_file_calibration_hash = MagicMock()
        monkeypatch.setattr(wf_module, "require_library_song_id", require_library_song_id)
        monkeypatch.setattr(wf_module, "discover_heads", discover_heads)
        monkeypatch.setattr(wf_module, "build_output_stream_lookup", build_output_stream_lookup)
        monkeypatch.setattr(wf_module, "load_output_streams_for_song", load_output_streams_for_song)
        monkeypatch.setattr(wf_module, "reconstruct_head_outputs_from_streams", reconstruct)
        monkeypatch.setattr(wf_module, "save_mood_tags", save_mood_tags)
        monkeypatch.setattr(wf_module, "update_file_calibration_hash", update_file_calibration_hash)
        monkeypatch.setattr(wf_module, "load_calibration_lookup", MagicMock(return_value={}))

        assert wf_module.write_calibrated_tags_wf(db, params) is False

        reconstruct.assert_not_called()
        save_mood_tags.assert_not_called()
        update_file_calibration_hash.assert_not_called()
        assert db.segment_scores_stats.mock_calls == []
