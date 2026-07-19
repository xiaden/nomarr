"""Tests for calibration apply chunking without DB-read caches."""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dto.tags_dto import Tags

apply_module = importlib.import_module("nomarr.workflows.calibration.apply_calibration_wf")


@pytest.mark.unit
@pytest.mark.mocked
class TestApplyCalibrationWorkflow:
    """Tests for chunk-limited calibration apply."""

    def test_flushes_deferred_writes_per_chunk_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Chunk size should bound each deferred batch flush even without read prefetching."""
        db = MagicMock()
        save_mood_tags_batch = MagicMock()
        update_file_calibration_hashes_batch = MagicMock()
        write_calls: list[str] = []

        monkeypatch.setattr(apply_module, "discover_heads", MagicMock(return_value=[{"head": "mood"}]))
        monkeypatch.setattr(apply_module, "load_calibrations_from_db_wf", MagicMock(return_value={}))
        monkeypatch.setattr(apply_module, "get_calibration_version", MagicMock(return_value="version-1"))
        monkeypatch.setattr(apply_module, "save_mood_tags_batch", save_mood_tags_batch)
        monkeypatch.setattr(
            apply_module,
            "update_file_calibration_hashes_batch",
            update_file_calibration_hashes_batch,
        )

        def _write_calibrated_tags(*, db: MagicMock, params: Any, batch_ctx: Any | None = None) -> None:
            assert batch_ctx is not None
            file_path = params.file_path
            write_calls.append(file_path)
            with batch_ctx._lock:
                batch_ctx.pending_mood_tags.append((file_path, Tags(items=())))
                batch_ctx.pending_calibration_hashes.append(file_path)

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
