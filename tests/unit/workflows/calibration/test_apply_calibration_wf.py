"""Tests for calibration apply chunking without DB-read caches."""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock

import pytest

apply_module = importlib.import_module("nomarr.workflows.calibration.apply_calibration_wf")


@pytest.mark.unit
@pytest.mark.mocked
class TestApplyCalibrationWorkflow:
    """Tests for chunk-limited calibration apply."""

    def test_flushes_deferred_writes_per_chunk_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Chunk size should bound each deferred batch flush even without read prefetching."""
        db = MagicMock()
        db.app.get_song_states.return_value = {apply_module.STATE_TAGS_CURRENT}
        save_mood_tags_batch = MagicMock()
        update_file_calibration_hashes_batch = MagicMock()
        transition_song_state = MagicMock()
        write_calls: list[str] = []

        monkeypatch.setattr(apply_module, "discover_heads", MagicMock(return_value=[{"head": "mood"}]))
        monkeypatch.setattr(apply_module, "load_calibrations_from_db_wf", MagicMock(return_value={}))
        monkeypatch.setattr(apply_module, "get_calibration_version", MagicMock(return_value="version-1"))
        monkeypatch.setattr(apply_module, "save_mood_tags_batch", save_mood_tags_batch)
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
                song_id = int(file_path.rsplit("-", 1)[1].split(".", 1)[0])
                batch_ctx.pending_mood_tags.append((song_id, None))
                batch_ctx.pending_calibration_hashes.append(song_id)
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
        assert [len(call.args[1]) for call in save_mood_tags_batch.call_args_list] == [2, 2, 1]
        assert [len(call.args[1]) for call in update_file_calibration_hashes_batch.call_args_list] == [2, 2, 1]
        assert transition_song_state.call_count == 5
        assert transition_song_state.call_args_list[0].args == (
            db,
            [0],
            apply_module.STATE_TAGS_CURRENT,
            apply_module.STATE_TAGS_NOT_FRESH,
        )

    def test_mood_flush_failure_reports_files_and_skips_hashes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = MagicMock()
        db.app.get_song_states.return_value = {apply_module.STATE_TAGS_CURRENT}
        save_mood_tags_batch = MagicMock(side_effect=RuntimeError("tag write failed"))
        update_hashes = MagicMock()
        transition_song_state = MagicMock()
        monkeypatch.setattr(apply_module, "discover_heads", MagicMock(return_value=[{"head": "mood"}]))
        monkeypatch.setattr(apply_module, "load_calibrations_from_db_wf", MagicMock(return_value={}))
        monkeypatch.setattr(apply_module, "get_calibration_version", MagicMock(return_value="version-1"))
        monkeypatch.setattr(apply_module, "save_mood_tags_batch", save_mood_tags_batch)
        monkeypatch.setattr(apply_module, "update_file_calibration_hashes_batch", update_hashes)
        monkeypatch.setattr(apply_module, "transition_song_state", transition_song_state)

        def _write(*, batch_ctx: Any, **_: Any) -> bool:
            with batch_ctx._lock:
                batch_ctx.pending_mood_tags.append((1, None))
                batch_ctx.pending_calibration_hashes.append(1)
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

    def test_hash_flush_failure_reports_files_after_mood_flush(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = MagicMock()
        db.app.get_song_states.return_value = {apply_module.STATE_TAGS_CURRENT}
        save_mood_tags_batch = MagicMock()
        update_hashes = MagicMock(side_effect=RuntimeError("state write failed"))
        transition_song_state = MagicMock()
        monkeypatch.setattr(apply_module, "discover_heads", MagicMock(return_value=[{"head": "mood"}]))
        monkeypatch.setattr(apply_module, "load_calibrations_from_db_wf", MagicMock(return_value={}))
        monkeypatch.setattr(apply_module, "get_calibration_version", MagicMock(return_value="version-1"))
        monkeypatch.setattr(apply_module, "save_mood_tags_batch", save_mood_tags_batch)
        monkeypatch.setattr(apply_module, "update_file_calibration_hashes_batch", update_hashes)
        monkeypatch.setattr(apply_module, "transition_song_state", transition_song_state)

        def _write(*, batch_ctx: Any, **_: Any) -> bool:
            with batch_ctx._lock:
                batch_ctx.pending_mood_tags.append((1, None))
                batch_ctx.pending_calibration_hashes.append(1)
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
        save_mood_tags_batch.assert_called_once()
        transition_song_state.assert_not_called()
