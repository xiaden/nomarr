"""Unit tests for nomarr.components.library.work_status_comp module."""

from __future__ import annotations

import pytest

from nomarr.components.library.work_status_comp import compute_work_status
from nomarr.helpers.dto.library_dto import LibraryStatsResult


def _make_stats(total: int = 10, needs_tagging: int = 2) -> LibraryStatsResult:
    return LibraryStatsResult(
        total_files=total,
        total_artists=0,
        total_albums=0,
        total_duration=0,
        total_size=0,
        needs_tagging_count=needs_tagging,
    )


class TestComputeWorkStatus:
    """Tests for compute_work_status."""

    @pytest.mark.unit
    def test_pipeline_libraries_populated_from_pipeline_states(self) -> None:
        """Library in pipeline_states gets its state reflected in result."""
        libraries = [
            {"_id": "libraries/1", "name": "Rock Library", "library_auto_write": False},
        ]
        result = compute_work_status(
            libraries=libraries,
            stats=_make_stats(total=10, needs_tagging=0),
            recently_tagged_count=0,
            pipeline_states={"libraries/1": "write_ready"},
        )
        assert len(result.pipeline_libraries) == 1
        assert result.pipeline_libraries[0].library_id == "libraries/1"
        assert result.pipeline_libraries[0].state == "write_ready"

    @pytest.mark.unit
    def test_pipeline_state_defaults_to_idle(self) -> None:
        """Library absent from pipeline_states gets state='idle' in result."""
        libraries = [
            {"_id": "libraries/1", "name": "Jazz Library", "library_auto_write": False},
        ]
        result = compute_work_status(
            libraries=libraries,
            stats=_make_stats(),
            recently_tagged_count=0,
            pipeline_states={},
        )
        assert result.pipeline_libraries[0].state == "idle"

    @pytest.mark.unit
    def test_library_docs_used_when_provided(self) -> None:
        """pipeline_libraries is built from library_docs, not libraries, when provided."""
        libraries = [
            {"_id": "libraries/1", "name": "Rock Library", "library_auto_write": False},
        ]
        library_docs = [
            {"_id": "libraries/2", "name": "Jazz Library", "library_auto_write": True},
        ]
        result = compute_work_status(
            libraries=libraries,
            stats=_make_stats(),
            recently_tagged_count=0,
            pipeline_states={},
            library_docs=library_docs,
        )
        assert len(result.pipeline_libraries) == 1
        assert result.pipeline_libraries[0].library_id == "libraries/2"
        assert result.pipeline_libraries[0].name == "Jazz Library"

    @pytest.mark.unit
    def test_library_auto_write_field_read(self) -> None:
        """Library with library_auto_write=True produces True in pipeline info."""
        libraries = [
            {"_id": "libraries/1", "name": "Auto Library", "library_auto_write": True},
        ]
        result = compute_work_status(
            libraries=libraries,
            stats=_make_stats(),
            recently_tagged_count=0,
            pipeline_states={},
        )
        assert result.pipeline_libraries[0].library_auto_write is True

    @pytest.mark.unit
    def test_no_pipeline_libraries_when_empty_docs(self) -> None:
        """Empty libraries with no library_docs yields empty pipeline_libraries."""
        result = compute_work_status(
            libraries=[],
            stats=_make_stats(total=0, needs_tagging=0),
            recently_tagged_count=0,
            pipeline_states={},
        )
        assert result.pipeline_libraries == []

    @pytest.mark.unit
    def test_scanning_library_identified(self) -> None:
        """Pipeline state drives scanning even when the scan doc says otherwise."""
        libraries = [
            {
                "_id": "libraries/1",
                "name": "Rock Library",
                "scan_status": "idle",
                "scan_progress": 50,
                "scan_total": 200,
                "library_auto_write": False,
            },
        ]
        result = compute_work_status(
            libraries=libraries,
            stats=_make_stats(),
            recently_tagged_count=0,
            pipeline_states={"libraries/1": "scanning"},
        )
        assert result.is_scanning
        assert len(result.scanning_libraries) == 1
        assert result.scanning_libraries[0].progress == 50
        assert result.scanning_libraries[0].total == 200

    @pytest.mark.unit
    def test_scan_status_ignored_without_scanning_pipeline_state(self) -> None:
        """scan_status alone does not mark a library as scanning."""
        libraries = [
            {
                "_id": "libraries/1",
                "name": "Rock Library",
                "scan_status": "scanning",
                "scan_progress": 50,
                "scan_total": 200,
                "library_auto_write": False,
            },
        ]
        result = compute_work_status(
            libraries=libraries,
            stats=_make_stats(),
            recently_tagged_count=0,
            pipeline_states={},
        )
        assert result.is_scanning is False
        assert result.scanning_libraries == []

    @pytest.mark.unit
    def test_scan_status_ignored_when_other_library_is_scanning(self) -> None:
        """Only the matching library pipeline state should mark it as scanning."""
        libraries = [
            {
                "_id": "libraries/1",
                "name": "Rock Library",
                "scan_status": "scanning",
                "scan_progress": 50,
                "scan_total": 200,
                "library_auto_write": False,
            },
        ]
        result = compute_work_status(
            libraries=libraries,
            stats=_make_stats(),
            recently_tagged_count=0,
            pipeline_states={"libraries/other": "scanning"},
        )
        assert result.is_scanning is False
        assert result.scanning_libraries == []

    @pytest.mark.unit
    def test_velocity_calculation(self) -> None:
        """Non-zero recently_tagged_count produces correct files_per_minute and ETA."""
        result = compute_work_status(
            libraries=[],
            stats=_make_stats(total=100, needs_tagging=60),
            recently_tagged_count=30,
            pipeline_states={},
            velocity_window_seconds=300,
        )
        # 30 files / (300/60 min) = 6.0 files/min
        assert result.files_per_minute == 6.0
        # 60 pending / 6.0 files/min = 10.0 min remaining
        assert result.estimated_minutes_remaining == 10.0

    @pytest.mark.unit
    def test_no_velocity_no_eta(self) -> None:
        """Zero tagged count produces 0.0 files_per_minute and None ETA."""
        result = compute_work_status(
            libraries=[],
            stats=_make_stats(total=10, needs_tagging=5),
            recently_tagged_count=0,
            pipeline_states={},
        )
        assert result.files_per_minute == 0.0
        assert result.estimated_minutes_remaining is None
