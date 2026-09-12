"""Tests for canonical-stream calibrated-tags workflow helpers."""

from __future__ import annotations

import importlib
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.ml_output_stream_dataclass import OutputStream
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    CalibrationMoodMarker,
    MoodAssignments,
    MoodReplacementCommand,
    MoodWriteResult,
    MoodWriteStatus,
)
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.helpers.dto.calibration_dto import WriteCalibratedTagsParams
from nomarr.helpers.dto.ml_dto import HeadOutput, LoadedOutputStream

stream_store_module = importlib.import_module("nomarr.components.ml.inference.ml_output_stream_store_comp")
wf_module = importlib.import_module("nomarr.workflows.calibration.write_calibrated_tags_wf")


def _song_identity(path: str = "example.flac") -> SongIdentity:
    return SongIdentity(
        library=LibraryIdentity(library_uuid="library-1", name="Music", root_path="/music"),
        normalized_path=path,
    )


def _make_tags(**items: str) -> Tags:
    """Create a Tags DTO from scalar string values."""
    return Tags(items=tuple(Tag(name=key, values=(value,)) for key, value in items.items()))


_CALIBRATION_VERSION = "0123456789abcdef0123456789abcdef"


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
                OutputStream(output_id="ml_model_outputs/out-1", output_index=0, values=[0.8, 0.7]),
                OutputStream(output_id="ml_model_outputs/out-2", output_index=1, values=[0.2, 0.3]),
            ]
        )
        monkeypatch.setattr(stream_store_module, "fetch_output_streams", fetch_output_streams)

        result = stream_store_module.load_output_streams_for_song(
            db,
            _song_identity(),
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
        fetch_output_streams.assert_called_once_with(db, _song_identity())

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
            _song_identity(),
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
            MagicMock(return_value=[OutputStream(output_id="ml_model_outputs/out-404", output_index=0, values=[0.5])]),
        )

        result = stream_store_module.load_output_streams_for_song(
            db,
            _song_identity(),
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
        db.library.tags.replace_mood_tags.return_value = MoodWriteResult("UPDATED", 1)
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
        mood_tags = _make_tags(**{"mood-strict": "happy"})
        _resolve_song_identity_for_path = MagicMock(return_value=_song_identity())
        discover_heads = MagicMock(return_value=head_infos)
        build_output_stream_lookup = MagicMock(return_value={"ml_model_outputs/out-1": ("mood_multiclass", "happy")})
        load_output_streams_for_song = MagicMock(return_value=output_streams)
        reconstruct = MagicMock(return_value=head_outputs)
        aggregate_mood_tags = MagicMock(return_value=mood_tags)
        get_calibration_version = MagicMock(return_value=_CALIBRATION_VERSION)
        update_file_calibration_hash = MagicMock()
        transition_song_state = MagicMock()
        db.app.song_state_membership = MagicMock(return_value={"tags_current"})
        monkeypatch.setattr(wf_module, "_resolve_song_identity_for_path", _resolve_song_identity_for_path)
        monkeypatch.setattr(wf_module, "discover_heads", discover_heads)
        monkeypatch.setattr(wf_module, "build_output_stream_lookup", build_output_stream_lookup)
        monkeypatch.setattr(wf_module, "load_output_streams_for_song", load_output_streams_for_song)
        monkeypatch.setattr(wf_module, "reconstruct_head_outputs_from_streams", reconstruct)
        monkeypatch.setattr(wf_module, "aggregate_mood_tags", aggregate_mood_tags)
        monkeypatch.setattr(wf_module, "get_calibration_version", get_calibration_version)
        monkeypatch.setattr(wf_module, "update_file_calibration_hash", update_file_calibration_hash)
        monkeypatch.setattr(wf_module, "transition_song_state", transition_song_state)
        monkeypatch.setattr(wf_module, "load_calibration_lookup", MagicMock(return_value={"happy": {"p5": 0.1}}))

        assert wf_module.write_calibrated_tags_wf(db, params) is True

        _resolve_song_identity_for_path.assert_called_once_with(db, "/music/example.flac")
        build_output_stream_lookup.assert_called_once_with(db, head_infos)
        load_output_streams_for_song.assert_called_once_with(
            db,
            _song_identity(),
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
        db.library.tags.replace_mood_tags.assert_called_once_with(
            _song_identity(),
            MoodAssignments(strict=("happy",)),
            CalibrationMoodMarker.calibrated(_CALIBRATION_VERSION),
        )
        update_file_calibration_hash.assert_called_once_with(db, _song_identity(), _CALIBRATION_VERSION)
        transition_song_state.assert_called_once_with(db, [_song_identity()], "tags_current", "tags_not_fresh")
        assert db.segment_scores_stats.mock_calls == []

    def test_none_aggregation_still_writes_none_tiers_and_marks_hash(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When aggregation produces no mood tags, None is still written to clear stale tiers."""
        db = MagicMock()
        db.library.tags.replace_mood_tags.return_value = MoodWriteResult("UPDATED", 0)
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
        _resolve_song_identity_for_path = MagicMock(return_value=_song_identity())
        discover_heads = MagicMock(return_value=head_infos)
        build_output_stream_lookup = MagicMock(return_value={"ml_model_outputs/out-1": ("mood_multiclass", "happy")})
        load_output_streams_for_song = MagicMock(return_value=output_streams)
        reconstruct = MagicMock(return_value=head_outputs)
        aggregate_mood_tags = MagicMock(return_value=None)
        get_calibration_version = MagicMock(return_value=_CALIBRATION_VERSION)
        update_file_calibration_hash = MagicMock()
        transition_song_state = MagicMock()
        db.app.song_state_membership = MagicMock(return_value={"tags_current"})
        monkeypatch.setattr(wf_module, "_resolve_song_identity_for_path", _resolve_song_identity_for_path)
        monkeypatch.setattr(wf_module, "discover_heads", discover_heads)
        monkeypatch.setattr(wf_module, "build_output_stream_lookup", build_output_stream_lookup)
        monkeypatch.setattr(wf_module, "load_output_streams_for_song", load_output_streams_for_song)
        monkeypatch.setattr(wf_module, "reconstruct_head_outputs_from_streams", reconstruct)
        monkeypatch.setattr(wf_module, "aggregate_mood_tags", aggregate_mood_tags)
        monkeypatch.setattr(wf_module, "get_calibration_version", get_calibration_version)
        monkeypatch.setattr(wf_module, "update_file_calibration_hash", update_file_calibration_hash)
        monkeypatch.setattr(wf_module, "transition_song_state", transition_song_state)
        monkeypatch.setattr(wf_module, "load_calibration_lookup", MagicMock(return_value={}))

        assert wf_module.write_calibrated_tags_wf(db, params) is True

        db.library.tags.replace_mood_tags.assert_called_once_with(
            _song_identity(),
            None,
            CalibrationMoodMarker.calibrated(_CALIBRATION_VERSION),
        )
        update_file_calibration_hash.assert_called_once_with(db, _song_identity(), _CALIBRATION_VERSION)
        transition_song_state.assert_called_once_with(db, [_song_identity()], "tags_current", "tags_not_fresh")

    def test_uncalibrated_version_publishes_uncalibrated_marker_without_hash(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When no global calibration version exists, mood is published uncalibrated and no hash is written."""
        db = MagicMock()
        db.library.tags.replace_mood_tags.return_value = MoodWriteResult("UPDATED", 1)
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
        monkeypatch.setattr(wf_module, "_resolve_song_identity_for_path", MagicMock(return_value=_song_identity()))
        monkeypatch.setattr(wf_module, "discover_heads", MagicMock(return_value=head_infos))
        monkeypatch.setattr(wf_module, "build_output_stream_lookup", MagicMock(return_value={}))
        monkeypatch.setattr(wf_module, "load_output_streams_for_song", MagicMock(return_value=output_streams))
        monkeypatch.setattr(wf_module, "reconstruct_head_outputs_from_streams", MagicMock(return_value=head_outputs))
        monkeypatch.setattr(
            wf_module, "aggregate_mood_tags", MagicMock(return_value=_make_tags(**{"mood-loose": "happy"}))
        )
        monkeypatch.setattr(wf_module, "get_calibration_version", MagicMock(return_value=None))
        update_file_calibration_hash = MagicMock()
        transition_song_state = MagicMock()
        monkeypatch.setattr(wf_module, "update_file_calibration_hash", update_file_calibration_hash)
        monkeypatch.setattr(wf_module, "transition_song_state", transition_song_state)
        monkeypatch.setattr(wf_module, "load_calibration_lookup", MagicMock(return_value={}))

        assert wf_module.write_calibrated_tags_wf(db, params) is True

        db.library.tags.replace_mood_tags.assert_called_once_with(
            _song_identity(),
            MoodAssignments(loose=("happy",)),
            CalibrationMoodMarker.uncalibrated(),
        )
        update_file_calibration_hash.assert_not_called()
        transition_song_state.assert_not_called()

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
        mood_tags_1 = _make_tags(**{"mood-strict": "happy"})
        mood_tags_2 = _make_tags(**{"mood-regular": "happy"})
        batch_ctx = wf_module.BatchContext(
            heads=head_infos,
            calibrations={"happy": {"p5": 0.1}},
            calibration_version=_CALIBRATION_VERSION,
        )
        _resolve_song_identity_for_path = MagicMock(
            side_effect=[_song_identity("example-1.flac"), _song_identity("example-2.flac")]
        )
        discover_heads = MagicMock()
        build_output_stream_lookup = MagicMock(return_value=lookup)
        load_output_streams_for_song = MagicMock(side_effect=[output_streams_1, output_streams_2])
        reconstruct = MagicMock(side_effect=[head_outputs_1, head_outputs_2])
        aggregate_mood_tags = MagicMock(side_effect=[mood_tags_1, mood_tags_2])
        update_file_calibration_hash = MagicMock()
        monkeypatch.setattr(wf_module, "_resolve_song_identity_for_path", _resolve_song_identity_for_path)
        monkeypatch.setattr(wf_module, "discover_heads", discover_heads)
        monkeypatch.setattr(wf_module, "build_output_stream_lookup", build_output_stream_lookup)
        monkeypatch.setattr(wf_module, "load_output_streams_for_song", load_output_streams_for_song)
        monkeypatch.setattr(wf_module, "reconstruct_head_outputs_from_streams", reconstruct)
        monkeypatch.setattr(wf_module, "aggregate_mood_tags", aggregate_mood_tags)
        monkeypatch.setattr(wf_module, "update_file_calibration_hash", update_file_calibration_hash)

        assert wf_module.write_calibrated_tags_wf(db, params_1, batch_ctx=batch_ctx) is True
        assert wf_module.write_calibrated_tags_wf(db, params_2, batch_ctx=batch_ctx) is True

        discover_heads.assert_not_called()
        build_output_stream_lookup.assert_called_once_with(db, head_infos)
        assert batch_ctx.output_stream_lookup is lookup
        assert load_output_streams_for_song.call_count == 2
        assert load_output_streams_for_song.call_args_list[0].kwargs["output_lookup"] is lookup
        assert load_output_streams_for_song.call_args_list[1].kwargs["output_lookup"] is lookup
        expected_commands = [
            MoodReplacementCommand(
                song=_song_identity("example-1.flac"),
                assignments=MoodAssignments(strict=("happy",)),
                marker=CalibrationMoodMarker.calibrated(_CALIBRATION_VERSION),
            ),
            MoodReplacementCommand(
                song=_song_identity("example-2.flac"),
                assignments=MoodAssignments(regular=("happy",)),
                marker=CalibrationMoodMarker.calibrated(_CALIBRATION_VERSION),
            ),
        ]
        assert batch_ctx.pending_mood_commands == expected_commands
        assert batch_ctx.pending_calibration_hashes == [
            (_song_identity("example-1.flac"), _CALIBRATION_VERSION),
            (_song_identity("example-2.flac"), _CALIBRATION_VERSION),
        ]
        db.library.tags.replace_mood_tags.assert_not_called()
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
        _resolve_song_identity_for_path = MagicMock(return_value=_song_identity())
        discover_heads = MagicMock(return_value=head_infos)
        build_output_stream_lookup = MagicMock(return_value={"ml_model_outputs/out-1": ("mood_multiclass", "happy")})
        load_output_streams_for_song = MagicMock(return_value=[])
        reconstruct = MagicMock()
        update_file_calibration_hash = MagicMock()
        monkeypatch.setattr(wf_module, "_resolve_song_identity_for_path", _resolve_song_identity_for_path)
        monkeypatch.setattr(wf_module, "discover_heads", discover_heads)
        monkeypatch.setattr(wf_module, "build_output_stream_lookup", build_output_stream_lookup)
        monkeypatch.setattr(wf_module, "load_output_streams_for_song", load_output_streams_for_song)
        monkeypatch.setattr(wf_module, "reconstruct_head_outputs_from_streams", reconstruct)
        monkeypatch.setattr(wf_module, "update_file_calibration_hash", update_file_calibration_hash)
        monkeypatch.setattr(wf_module, "load_calibration_lookup", MagicMock(return_value={}))

        assert wf_module.write_calibrated_tags_wf(db, params) is False

        reconstruct.assert_not_called()
        db.library.tags.replace_mood_tags.assert_not_called()
        update_file_calibration_hash.assert_not_called()
        assert db.segment_scores_stats.mock_calls == []

    def test_returns_false_when_calibrated_outputs_are_missing(
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
        head_infos = [_FakeHeadInfo(name="mood_multiclass", labels=["happy"], model_path="/models/mood.onnx")]
        monkeypatch.setattr(wf_module, "_resolve_song_identity_for_path", MagicMock(return_value=_song_identity()))
        monkeypatch.setattr(wf_module, "discover_heads", MagicMock(return_value=head_infos))
        monkeypatch.setattr(wf_module, "build_output_stream_lookup", MagicMock(return_value={}))
        monkeypatch.setattr(wf_module, "load_output_streams_for_song", MagicMock(return_value=[MagicMock()]))
        monkeypatch.setattr(wf_module, "reconstruct_head_outputs_from_streams", MagicMock(return_value=[]))
        update_file_calibration_hash = MagicMock()
        monkeypatch.setattr(wf_module, "update_file_calibration_hash", update_file_calibration_hash)
        monkeypatch.setattr(wf_module, "load_calibration_lookup", MagicMock(return_value={}))

        assert wf_module.write_calibrated_tags_wf(db, params) is False

        db.library.tags.replace_mood_tags.assert_not_called()
        update_file_calibration_hash.assert_not_called()

    @pytest.mark.parametrize(
        "status",
        ["MISSING_LOCATOR", "INVALID_VALUE", "INFRA_FAILURE", "AMBIGUOUS_COMMIT"],
    )
    def test_single_file_non_success_mood_status_skips_hash_and_returns_false(
        self,
        monkeypatch: pytest.MonkeyPatch,
        status: str,
    ) -> None:
        """A non-success mood publication must not write a hash, mark reconciliation, or report success."""
        db = MagicMock()
        db.library.tags.replace_mood_tags.return_value = MoodWriteResult(cast("MoodWriteStatus", status), 0)
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
        update_file_calibration_hash = MagicMock()
        transition_song_state = MagicMock()
        monkeypatch.setattr(wf_module, "_resolve_song_identity_for_path", MagicMock(return_value=_song_identity()))
        monkeypatch.setattr(wf_module, "discover_heads", MagicMock(return_value=head_infos))
        monkeypatch.setattr(
            wf_module,
            "build_output_stream_lookup",
            MagicMock(return_value={"ml_model_outputs/out-1": ("mood_multiclass", "happy")}),
        )
        monkeypatch.setattr(wf_module, "load_output_streams_for_song", MagicMock(return_value=output_streams))
        monkeypatch.setattr(wf_module, "reconstruct_head_outputs_from_streams", MagicMock(return_value=head_outputs))
        monkeypatch.setattr(
            wf_module, "aggregate_mood_tags", MagicMock(return_value=_make_tags(**{"mood-strict": "happy"}))
        )
        monkeypatch.setattr(wf_module, "get_calibration_version", MagicMock(return_value=_CALIBRATION_VERSION))
        monkeypatch.setattr(wf_module, "update_file_calibration_hash", update_file_calibration_hash)
        monkeypatch.setattr(wf_module, "transition_song_state", transition_song_state)
        monkeypatch.setattr(wf_module, "load_calibration_lookup", MagicMock(return_value={"happy": {"p5": 0.1}}))

        result = wf_module.write_calibrated_tags_wf(db, params)

        assert result is False
        db.library.tags.replace_mood_tags.assert_called_once_with(
            _song_identity(),
            MoodAssignments(strict=("happy",)),
            CalibrationMoodMarker.calibrated(_CALIBRATION_VERSION),
        )
        update_file_calibration_hash.assert_not_called()
        transition_song_state.assert_not_called()
