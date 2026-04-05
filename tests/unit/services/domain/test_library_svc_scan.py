"""Tests for ``nomarr.services.domain.library_svc.scan`` mixin behavior."""

from __future__ import annotations

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

        with patch("nomarr.services.domain.library_svc.scan.scan_setup_workflow") as mock_scan_setup:
            result = service.start_quick_scan("lib1")

        mock_scan_setup.assert_called_once_with(service.db, "lib1", scan_type="quick")
        mock_bts.start_task.assert_called_once()
        managed_task = mock_bts.start_task.call_args.args[0]
        assert isinstance(managed_task, ManagedTask)
        assert managed_task.task_id == "scan_library_lib1"
        assert result.job_ids == ["scan_library_lib1"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_full_scan_registers_managed_task(self) -> None:
        """Full scan should register a ManagedTask with the expected task id."""
        mock_bts = MagicMock()
        service = _make_service(background_tasks=mock_bts)

        with patch("nomarr.services.domain.library_svc.scan.scan_setup_workflow") as mock_scan_setup:
            result = service.start_full_scan("lib1")

        mock_scan_setup.assert_called_once_with(service.db, "lib1", scan_type="full")
        mock_bts.start_task.assert_called_once()
        managed_task = mock_bts.start_task.call_args.args[0]
        assert isinstance(managed_task, ManagedTask)
        assert managed_task.task_id == "scan_library_lib1"
        assert result.job_ids == ["scan_library_lib1"]
