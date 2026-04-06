"""Tests for ``nomarr.services.domain.library_svc.scan`` mixin behavior."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers import ManagedTask
from nomarr.services.domain.library_svc import LibraryService, LibraryServiceConfig


def _make_service(*, background_tasks: MagicMock | None = None) -> LibraryService:
    """Build a minimal LibraryService for scan dispatch tests."""
    return LibraryService(
        cfg=LibraryServiceConfig(
            models_dir="models",
            namespace="nom",
            tagger_version="tagger-v1",
            library_root="/music",
        ),
        db=MagicMock(),
        background_tasks=background_tasks or MagicMock(),
    )


class TestScanDispatch:
    """Tests for ManagedTask-backed scan dispatch methods."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_quick_scan_registers_managed_task(self) -> None:
        """Quick scan should register a ManagedTask with the expected task id."""
        mock_bts = MagicMock()
        service = _make_service(background_tasks=mock_bts)

        with (
            patch("nomarr.services.domain.library_svc.scan.scan_setup_workflow") as mock_scan_setup,
            patch(
                "nomarr.services.domain.library_svc.scan.on_scan_complete_pipeline_hook",
            ) as mock_on_complete_hook,
        ):
            result = service.start_quick_scan("lib1")

        mock_scan_setup.assert_called_once_with(service.db, "lib1", scan_type="quick")
        mock_bts.start_task.assert_called_once()
        managed_task = mock_bts.start_task.call_args.args[0]
        assert isinstance(managed_task, ManagedTask)
        assert managed_task.task_id == "scan_library_lib1"
        assert managed_task.on_complete is not None
        managed_task.on_complete()
        mock_on_complete_hook.assert_called_once_with(service.db, "lib1")
        assert result.job_ids == ["scan_library_lib1"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_full_scan_registers_managed_task(self) -> None:
        """Full scan should register a ManagedTask with the expected task id."""
        mock_bts = MagicMock()
        service = _make_service(background_tasks=mock_bts)

        with (
            patch("nomarr.services.domain.library_svc.scan.scan_setup_workflow") as mock_scan_setup,
            patch(
                "nomarr.services.domain.library_svc.scan.on_scan_complete_pipeline_hook",
            ) as mock_on_complete_hook,
        ):
            result = service.start_full_scan("lib1")

        mock_scan_setup.assert_called_once_with(service.db, "lib1", scan_type="full")
        mock_bts.start_task.assert_called_once()
        managed_task = mock_bts.start_task.call_args.args[0]
        assert isinstance(managed_task, ManagedTask)
        assert managed_task.task_id == "scan_library_lib1"
        assert managed_task.on_complete is not None
        managed_task.on_complete()
        mock_on_complete_hook.assert_called_once_with(service.db, "lib1")
        assert result.job_ids == ["scan_library_lib1"]


class TestScanStateQueries:
    """Tests for scan-status reads derived from pipeline state."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_scan_running_returns_true_when_pipeline_has_scanning_library(self) -> None:
        """A non-empty scanning pipeline state should report an active scan."""
        service = _make_service()
        mock_get_libraries_in_state = cast(
            "MagicMock",
            service.db.library_pipeline_states.get_libraries_in_state,
        )
        mock_get_libraries_in_state.return_value = ["libraries/lib1"]

        assert service._is_scan_running() is True

        mock_get_libraries_in_state.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_is_scan_running_returns_false_when_pipeline_is_idle(self) -> None:
        """An empty scanning pipeline result should report no active scan."""
        service = _make_service()
        mock_get_libraries_in_state = cast(
            "MagicMock",
            service.db.library_pipeline_states.get_libraries_in_state,
        )
        mock_get_libraries_in_state.return_value = []

        assert service._is_scan_running() is False

        mock_get_libraries_in_state.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_status_aggregate_counts_running_jobs_from_pipeline_state(self) -> None:
        """Aggregate running_jobs should equal the number of scanning pipeline libraries."""
        service = _make_service()
        mock_get_libraries_in_state = cast(
            "MagicMock",
            service.db.library_pipeline_states.get_libraries_in_state,
        )
        mock_get_libraries_in_state.return_value = [
            "libraries/lib1",
            "libraries/lib2",
        ]

        result = service.get_status()

        assert result.configured is True
        assert result.running_jobs == 2
        assert result.pending_jobs == 0

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_status_library_running_jobs_ignores_scan_status_field(self) -> None:
        """Per-library running_jobs should come from pipeline state, not scan_status text."""
        service = _make_service()
        mock_get_libraries_in_state = cast(
            "MagicMock",
            service.db.library_pipeline_states.get_libraries_in_state,
        )
        mock_get_library = cast("MagicMock", service.db.libraries.get_library)
        mock_get_libraries_in_state.return_value = ["libraries/lib2"]
        mock_get_library.return_value = {
            "_id": "libraries/lib1",
            "name": "Rock Library",
            "scan_status": "scanning",
            "scan_progress": 5,
            "scan_total": 10,
            "scan_error": None,
            "scanned_at": None,
        }

        result = service.get_status("libraries/lib1")

        assert result.scan_status == "scanning"
        assert result.running_jobs == 0

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_status_library_running_jobs_reflects_pipeline_state_even_when_scan_status_is_idle(self) -> None:
        """Per-library running_jobs should be 1 when the requested library is in the scanning pipeline state."""
        service = _make_service()
        mock_get_libraries_in_state = cast(
            "MagicMock",
            service.db.library_pipeline_states.get_libraries_in_state,
        )
        mock_get_library = cast("MagicMock", service.db.libraries.get_library)
        mock_get_libraries_in_state.return_value = ["libraries/lib1"]
        mock_get_library.return_value = {
            "_id": "libraries/lib1",
            "name": "Rock Library",
            "scan_status": "idle",
            "scan_progress": 0,
            "scan_total": 0,
            "scan_error": None,
            "scanned_at": None,
        }

        result = service.get_status("libraries/lib1")

        assert result.scan_status == "idle"
        assert result.running_jobs == 1
