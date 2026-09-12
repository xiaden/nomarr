"""Tests for calibration apply chunking without DB-read caches."""

from __future__ import annotations

import importlib
import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    CalibrationMoodMarker,
    MoodBatchResult,
    MoodReplacementCommand,
)

apply_module = importlib.import_module("nomarr.workflows.calibration.apply_calibration_wf")

_CALIBRATION_VERSION = "0123456789abcdef0123456789abcdef"


def _song_identity(index: int) -> SongIdentity:
    return SongIdentity(
        library=LibraryIdentity(library_uuid="library-1", name="Music", root_path="/music"),
        normalized_path=f"file-{index}.flac",
    )


@pytest.mark.unit
@pytest.mark.mocked
class TestApplyCalibrationWorkflow:
    """Tests for chunk-limited calibration apply."""

    def test_flushes_deferred_writes_per_chunk_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Chunk size should bound each deferred batch flush even without read prefetching."""
        db = MagicMock()
        db.app.song_state_membership.return_value = {apply_module.STATE_TAGS_CURRENT}
        db.library.tags.replace_mood_tags_batch.return_value = MoodBatchResult("UPDATED")
        update_file_calibration_hashes_batch = MagicMock()
        transition_song_state = MagicMock()
        write_calls: list[str] = []

        monkeypatch.setattr(apply_module, "discover_heads", MagicMock(return_value=[{"head": "mood"}]))
        monkeypatch.setattr(apply_module, "load_calibrations_from_db_wf", MagicMock(return_value={}))
        monkeypatch.setattr(apply_module, "get_calibration_version", MagicMock(return_value=_CALIBRATION_VERSION))
        monkeypatch.setattr(apply_module, "transition_song_state", transition_song_state)
        monkeypatch.setattr(
            apply_module,
            "update_file_calibration_hashes_batch",
            update_file_calibration_hashes_batch,
        )

        def _write_calibrated_tags(*, db: MagicMock, params: Any, batch_ctx: Any | None = None) -> bool:
            assert batch_ctx is not None
            file_path = params.file_path
            write_calls.append(file_path)
            with batch_ctx._lock:
                index = int(file_path.rsplit("-", 1)[1].split(".", 1)[0])
                batch_ctx.pending_mood_commands.append(
                    MoodReplacementCommand(
                        song=_song_identity(index),
                        assignments=None,
                        marker=CalibrationMoodMarker.calibrated(_CALIBRATION_VERSION),
                    )
                )
                batch_ctx.pending_calibration_hashes.append((_song_identity(index), _CALIBRATION_VERSION))
            return True

        monkeypatch.setattr(apply_module, "write_calibrated_tags_wf", _write_calibrated_tags)

        paths = [f"/music/file-{idx}.flac" for idx in range(5)]
        result = apply_module.apply_calibration_wf(
            db=db,
            paths=paths,
            models_dir="/models",
            namespace="nom",
            version_tag_key="nom_version",
            calibrate_heads=False,
            max_write_workers=1,
            prefetch_chunk_size=2,
        )

        assert result.processed == 5
        assert result.failed == 0
        assert write_calls == paths
        assert [len(call.args[0]) for call in db.library.tags.replace_mood_tags_batch.call_args_list] == [2, 2, 1]
        assert [len(call.args[1]) for call in update_file_calibration_hashes_batch.call_args_list] == [2, 2, 1]
        assert transition_song_state.call_count == 5
        assert transition_song_state.call_args_list[0].args == (
            db,
            [_song_identity(0)],
            apply_module.STATE_TAGS_CURRENT,
            apply_module.STATE_TAGS_NOT_FRESH,
        )

    def test_mood_flush_failure_reports_files_and_skips_hashes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = MagicMock()
        db.app.song_state_membership.return_value = {apply_module.STATE_TAGS_CURRENT}
        db.library.tags.replace_mood_tags_batch.return_value = MoodBatchResult("INFRA_FAILURE", 1)
        update_hashes = MagicMock()
        transition_song_state = MagicMock()
        monkeypatch.setattr(apply_module, "discover_heads", MagicMock(return_value=[{"head": "mood"}]))
        monkeypatch.setattr(apply_module, "load_calibrations_from_db_wf", MagicMock(return_value={}))
        monkeypatch.setattr(apply_module, "get_calibration_version", MagicMock(return_value=_CALIBRATION_VERSION))
        monkeypatch.setattr(apply_module, "update_file_calibration_hashes_batch", update_hashes)
        monkeypatch.setattr(apply_module, "transition_song_state", transition_song_state)

        def _write(*, batch_ctx: Any, **_: Any) -> bool:
            with batch_ctx._lock:
                batch_ctx.pending_mood_commands.append(
                    MoodReplacementCommand(
                        song=_song_identity(1),
                        assignments=None,
                        marker=CalibrationMoodMarker.calibrated(_CALIBRATION_VERSION),
                    )
                )
                batch_ctx.pending_calibration_hashes.append((_song_identity(1), _CALIBRATION_VERSION))
            return True

        monkeypatch.setattr(apply_module, "write_calibrated_tags_wf", _write)
        result = apply_module.apply_calibration_wf(
            db=db,
            paths=["/music/file.flac"],
            models_dir="/models",
            namespace="nom",
            version_tag_key="nom_version",
            calibrate_heads=False,
            max_write_workers=1,
            prefetch_chunk_size=1,
        )

        assert (result.processed, result.failed) == (0, 1)
        update_hashes.assert_not_called()
        transition_song_state.assert_not_called()

    def test_invalid_value_batch_reports_files_without_hashes_or_transition(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An INVALID_VALUE batch fails the whole chunk: no hash update, no reconciliation marking, no retry."""
        db = MagicMock()
        db.app.song_state_membership.return_value = {apply_module.STATE_TAGS_CURRENT}
        db.library.tags.replace_mood_tags_batch.return_value = MoodBatchResult("INVALID_VALUE", 1)
        update_hashes = MagicMock()
        transition_song_state = MagicMock()
        monkeypatch.setattr(apply_module, "discover_heads", MagicMock(return_value=[{"head": "mood"}]))
        monkeypatch.setattr(apply_module, "load_calibrations_from_db_wf", MagicMock(return_value={}))
        monkeypatch.setattr(apply_module, "get_calibration_version", MagicMock(return_value=_CALIBRATION_VERSION))
        monkeypatch.setattr(apply_module, "update_file_calibration_hashes_batch", update_hashes)
        monkeypatch.setattr(apply_module, "transition_song_state", transition_song_state)

        def _write(*, batch_ctx: Any, **_: Any) -> bool:
            with batch_ctx._lock:
                batch_ctx.pending_mood_commands.append(
                    MoodReplacementCommand(
                        song=_song_identity(1),
                        assignments=None,
                        marker=CalibrationMoodMarker.calibrated(_CALIBRATION_VERSION),
                    )
                )
                batch_ctx.pending_calibration_hashes.append((_song_identity(1), _CALIBRATION_VERSION))
            return True

        monkeypatch.setattr(apply_module, "write_calibrated_tags_wf", _write)
        result = apply_module.apply_calibration_wf(
            db=db,
            paths=["/music/file.flac"],
            models_dir="/models",
            namespace="nom",
            version_tag_key="nom_version",
            calibrate_heads=False,
            max_write_workers=1,
            prefetch_chunk_size=1,
        )

        assert (result.processed, result.failed) == (0, 1)
        db.library.tags.replace_mood_tags_batch.assert_called_once()
        update_hashes.assert_not_called()
        transition_song_state.assert_not_called()

    def test_missing_locator_batch_reports_files_without_retry_or_hashes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A typed MISSING_LOCATOR batch is a failure for the whole chunk and is not retried."""
        db = MagicMock()
        db.app.song_state_membership.return_value = {apply_module.STATE_TAGS_CURRENT}
        db.library.tags.replace_mood_tags_batch.return_value = MoodBatchResult("MISSING_LOCATOR", 1)
        update_hashes = MagicMock()
        transition_song_state = MagicMock()
        monkeypatch.setattr(apply_module, "discover_heads", MagicMock(return_value=[{"head": "mood"}]))
        monkeypatch.setattr(apply_module, "load_calibrations_from_db_wf", MagicMock(return_value={}))
        monkeypatch.setattr(apply_module, "get_calibration_version", MagicMock(return_value=_CALIBRATION_VERSION))
        monkeypatch.setattr(apply_module, "update_file_calibration_hashes_batch", update_hashes)
        monkeypatch.setattr(apply_module, "transition_song_state", transition_song_state)

        def _write(*, batch_ctx: Any, **_: Any) -> bool:
            with batch_ctx._lock:
                batch_ctx.pending_mood_commands.append(
                    MoodReplacementCommand(
                        song=_song_identity(1),
                        assignments=None,
                        marker=CalibrationMoodMarker.calibrated(_CALIBRATION_VERSION),
                    )
                )
                batch_ctx.pending_calibration_hashes.append((_song_identity(1), _CALIBRATION_VERSION))
            return True

        monkeypatch.setattr(apply_module, "write_calibrated_tags_wf", _write)
        result = apply_module.apply_calibration_wf(
            db=db,
            paths=["/music/file.flac"],
            models_dir="/models",
            namespace="nom",
            version_tag_key="nom_version",
            calibrate_heads=False,
            max_write_workers=1,
            prefetch_chunk_size=1,
        )

        assert (result.processed, result.failed) == (0, 1)
        db.library.tags.replace_mood_tags_batch.assert_called_once()
        update_hashes.assert_not_called()
        transition_song_state.assert_not_called()

    def test_ambiguous_commit_is_not_blindly_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AMBIGUOUS_COMMIT is reported as a failure with no retry, hash, or transition."""
        db = MagicMock()
        db.app.song_state_membership.return_value = {apply_module.STATE_TAGS_CURRENT}
        db.library.tags.replace_mood_tags_batch.return_value = MoodBatchResult("AMBIGUOUS_COMMIT", 1)
        update_hashes = MagicMock()
        transition_song_state = MagicMock()
        monkeypatch.setattr(apply_module, "discover_heads", MagicMock(return_value=[{"head": "mood"}]))
        monkeypatch.setattr(apply_module, "load_calibrations_from_db_wf", MagicMock(return_value={}))
        monkeypatch.setattr(apply_module, "get_calibration_version", MagicMock(return_value=_CALIBRATION_VERSION))
        monkeypatch.setattr(apply_module, "update_file_calibration_hashes_batch", update_hashes)
        monkeypatch.setattr(apply_module, "transition_song_state", transition_song_state)

        def _write(*, batch_ctx: Any, **_: Any) -> bool:
            with batch_ctx._lock:
                batch_ctx.pending_mood_commands.append(
                    MoodReplacementCommand(
                        song=_song_identity(1),
                        assignments=None,
                        marker=CalibrationMoodMarker.calibrated(_CALIBRATION_VERSION),
                    )
                )
                batch_ctx.pending_calibration_hashes.append((_song_identity(1), _CALIBRATION_VERSION))
            return True

        monkeypatch.setattr(apply_module, "write_calibrated_tags_wf", _write)
        result = apply_module.apply_calibration_wf(
            db=db,
            paths=["/music/file.flac"],
            models_dir="/models",
            namespace="nom",
            version_tag_key="nom_version",
            calibrate_heads=False,
            max_write_workers=1,
            prefetch_chunk_size=1,
        )

        assert (result.processed, result.failed) == (0, 1)
        db.library.tags.replace_mood_tags_batch.assert_called_once()
        update_hashes.assert_not_called()
        transition_song_state.assert_not_called()

    def test_hash_flush_failure_reports_files_after_mood_flush(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = MagicMock()
        db.app.song_state_membership.return_value = {apply_module.STATE_TAGS_CURRENT}
        db.library.tags.replace_mood_tags_batch.return_value = MoodBatchResult("UPDATED")
        update_hashes = MagicMock(side_effect=RuntimeError("state write failed"))
        transition_song_state = MagicMock()
        monkeypatch.setattr(apply_module, "discover_heads", MagicMock(return_value=[{"head": "mood"}]))
        monkeypatch.setattr(apply_module, "load_calibrations_from_db_wf", MagicMock(return_value={}))
        monkeypatch.setattr(apply_module, "get_calibration_version", MagicMock(return_value=_CALIBRATION_VERSION))
        monkeypatch.setattr(apply_module, "update_file_calibration_hashes_batch", update_hashes)
        monkeypatch.setattr(apply_module, "transition_song_state", transition_song_state)

        def _write(*, batch_ctx: Any, **_: Any) -> bool:
            with batch_ctx._lock:
                batch_ctx.pending_mood_commands.append(
                    MoodReplacementCommand(
                        song=_song_identity(1),
                        assignments=None,
                        marker=CalibrationMoodMarker.calibrated(_CALIBRATION_VERSION),
                    )
                )
                batch_ctx.pending_calibration_hashes.append((_song_identity(1), _CALIBRATION_VERSION))
            return True

        monkeypatch.setattr(apply_module, "write_calibrated_tags_wf", _write)
        result = apply_module.apply_calibration_wf(
            db=db,
            paths=["/music/file.flac"],
            models_dir="/models",
            namespace="nom",
            version_tag_key="nom_version",
            calibrate_heads=False,
            max_write_workers=1,
            prefetch_chunk_size=1,
        )

        assert (result.processed, result.failed) == (0, 1)
        db.library.tags.replace_mood_tags_batch.assert_called_once()
        transition_song_state.assert_not_called()


@pytest.mark.unit
def test_calibration_callers_have_no_generic_mood_writers() -> None:
    """Calibration callers must use the exact owner API, never the legacy generic mood writers."""
    write_module = importlib.import_module("nomarr.workflows.calibration.write_calibrated_tags_wf")
    for module in (apply_module, write_module):
        source = inspect.getsource(module)
        assert "save_mood_tags" not in source
        assert "replace_mood_tags" in source
