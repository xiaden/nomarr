"""Tests for calibrated-tags workflow cache fallback behavior."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dto.tags_dto import Tag, Tags

wf_module = importlib.import_module("nomarr.workflows.calibration.write_calibrated_tags_wf")


def _make_tags(**items: object) -> Tags:
    """Create a Tags DTO from scalar test values."""
    return Tags(items=tuple(Tag(key=key, value=(value,)) for key, value in items.items()))


@pytest.mark.unit
@pytest.mark.mocked
class TestLoadLibraryState:
    """Tests for library-state loading with optional batch caches."""

    def test_falls_back_to_db_tags_when_prefetched_tag_cache_misses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing batch tag entry must not be treated as authoritative empty tags."""
        db = MagicMock()
        file_path = "/music/example.flac"
        file_doc = {"_id": "library_files/1", "path": file_path}
        batch_ctx = wf_module.BatchContext(
            heads=[],
            calibrations={},
            calibration_version=None,
            prefetched_file_docs={file_path: file_doc},
            prefetched_tags={},
        )
        get_nomarr_tags = MagicMock(return_value=_make_tags(**{"nom:energy": 0.75}))
        monkeypatch.setattr(wf_module, "get_nomarr_tags", get_nomarr_tags)

        result = wf_module._load_library_state(db, file_path, batch_ctx=batch_ctx)

        assert result.file_id == "library_files/1"
        assert result.all_tags == {"energy": 0.75}
        get_nomarr_tags.assert_called_once_with(db, "library_files/1")

    def test_falls_back_to_db_file_lookup_when_prefetched_file_cache_misses(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A missing batch file-doc entry must fall back to the single-file component."""
        db = MagicMock()
        file_path = "/music/example.flac"
        file_doc = {"_id": "library_files/2", "path": file_path}
        batch_ctx = wf_module.BatchContext(
            heads=[],
            calibrations={},
            calibration_version=None,
            prefetched_file_docs={},
            prefetched_tags={"library_files/2": _make_tags(**{"nom:tempo": 120})},
        )
        get_library_file = MagicMock(return_value=file_doc)
        get_nomarr_tags = MagicMock()
        monkeypatch.setattr(wf_module, "get_library_file", get_library_file)
        monkeypatch.setattr(wf_module, "get_nomarr_tags", get_nomarr_tags)

        result = wf_module._load_library_state(db, file_path, batch_ctx=batch_ctx)

        assert result.file_id == "library_files/2"
        assert result.all_tags == {"tempo": 120}
        get_library_file.assert_called_once_with(db, file_path)
        get_nomarr_tags.assert_not_called()
