"""Tests for calibrated-tags workflow library-state loading."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dto.tags_dto import Tag, Tags

wf_module = importlib.import_module("nomarr.workflows.calibration.write_calibrated_tags_wf")

type TagScalar = str | int | float | bool


def _make_tags(**items: TagScalar) -> Tags:
    """Create a Tags DTO from scalar test values."""
    return Tags(items=tuple(Tag(key=key, value=(value,)) for key, value in items.items()))


@pytest.mark.unit
@pytest.mark.mocked
class TestLoadLibraryState:
    """Tests for library-state loading."""

    def test_loads_library_file_and_tags_via_components(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The helper should always read live file state through component wrappers."""
        db = MagicMock()
        file_path = "/music/example.flac"
        file_doc = {"_id": "library_files/1", "path": file_path}
        get_library_file = MagicMock(return_value=file_doc)
        get_nomarr_tags = MagicMock(return_value=_make_tags(**{"nom:energy": 0.75}))
        monkeypatch.setattr(wf_module, "get_library_file", get_library_file)
        monkeypatch.setattr(wf_module, "get_nomarr_tags", get_nomarr_tags)

        result = wf_module._load_library_state(db, file_path)

        assert result.file_id == "library_files/1"
        assert result.all_tags == {"energy": 0.75}
        get_library_file.assert_called_once_with(db, file_path)
        get_nomarr_tags.assert_called_once_with(db, "library_files/1")

    def test_batch_context_does_not_short_circuit_db_reads(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Batch context carries invariants only and must not act as a DB-read cache."""
        db = MagicMock()
        file_path = "/music/example.flac"
        file_doc = {"_id": "library_files/2", "path": file_path}
        batch_ctx = wf_module.BatchContext(
            heads=[],
            calibrations={},
            calibration_version=None,
        )
        get_library_file = MagicMock(return_value=file_doc)
        get_nomarr_tags = MagicMock(return_value=_make_tags(**{"nom:tempo": 120}))
        monkeypatch.setattr(wf_module, "get_library_file", get_library_file)
        monkeypatch.setattr(wf_module, "get_nomarr_tags", get_nomarr_tags)

        result = wf_module._load_library_state(db, file_path, batch_ctx=batch_ctx)

        assert result.file_id == "library_files/2"
        assert result.all_tags == {"tempo": 120}
        get_library_file.assert_called_once_with(db, file_path)
        get_nomarr_tags.assert_called_once_with(db, "library_files/2")
