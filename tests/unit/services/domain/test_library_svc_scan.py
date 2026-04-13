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
    def test_get_status_aggregate_counts_running_jobs_from_pipeline_state(self) -> None:
        """Aggregate running_jobs should equal the number of scanning pipeline libraries."""
        service = _make_service()
        with patch(
            "nomarr.services.domain.library_svc.scan.get_scanning_library_ids",
            return_value={"libraries/lib1", "libraries/lib2"},
        ):
            result = service.get_status()

        assert result.configured is True
        assert result.running_jobs == 2
        assert result.pending_jobs == 0

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_status_library_running_jobs_ignores_scan_status_field(self) -> None:
        """Per-library running_jobs should come from pipeline state, not scan_status text."""
        service = _make_service()
        library = {
            "_id": "libraries/lib1",
            "_key": "lib1",
            "_rev": "_abc",
            "name": "Rock Library",
            "root_path": "/music",
            "is_enabled": True,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "scan_status": "scanning",
            "scan_progress": 5,
            "scan_total": 10,
            "scan_error": None,
            "scanned_at": None,
        }

        with (
            patch("nomarr.services.domain.library_svc.scan.resolve_library_for_scan", return_value=library),
            patch(
                "nomarr.services.domain.library_svc.scan.get_scanning_library_ids",
                return_value={"libraries/lib2"},
            ),
        ):
            result = service.get_status("libraries/lib1")

        assert result.scan_status == "scanning"
        assert result.running_jobs == 0

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_status_library_running_jobs_reflects_pipeline_state_even_when_scan_status_is_idle(self) -> None:
        """Per-library running_jobs should be 1 when the requested library is in the scanning pipeline state."""
        service = _make_service()
        library = {
            "_id": "libraries/lib1",
            "_key": "lib1",
            "_rev": "_abc",
            "name": "Rock Library",
            "root_path": "/music",
            "is_enabled": True,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "scan_status": "idle",
            "scan_progress": 0,
            "scan_total": 0,
            "scan_error": None,
            "scanned_at": None,
        }

        with (
            patch("nomarr.services.domain.library_svc.scan.resolve_library_for_scan", return_value=library),
            patch(
                "nomarr.services.domain.library_svc.scan.get_scanning_library_ids",
                return_value={"libraries/lib1"},
            ),
        ):
            result = service.get_status("libraries/lib1")

        assert result.scan_status == "idle"
        assert result.running_jobs == 1

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_status_returns_unconfigured_when_library_root_is_none(self) -> None:
        service = LibraryService(
            cfg=LibraryServiceConfig(
                models_dir="models",
                namespace="nom",
                tagger_version="tagger-v1",
                library_root=None,
            ),
            db=MagicMock(),
            background_tasks=MagicMock(),
        )

        result = service.get_status()

        assert result.configured is False
        assert result.running_jobs == 0


class TestGetScanHistory:
    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_scan_history_delegates_to_component_with_limit(self) -> None:
        service = _make_service()
        expected = [
            {
                "library_id": "libraries/lib1",
                "name": "Rock Library",
                "scan_status": "idle",
            },
        ]

        with patch(
            "nomarr.services.domain.library_svc.scan.get_library_scan_histories",
            return_value=expected,
        ) as mock_get_library_scan_histories:
            result = service.get_scan_history(limit=5)

        mock_get_library_scan_histories.assert_called_once_with(service.db, limit=5)
        assert result == expected

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_scan_history_uses_default_limit_of_100(self) -> None:
        service = _make_service()

        with patch(
            "nomarr.services.domain.library_svc.scan.get_library_scan_histories",
            return_value=[],
        ) as mock_get_library_scan_histories:
            result = service.get_scan_history()

        mock_get_library_scan_histories.assert_called_once_with(service.db, limit=100)
        assert result == []


class TestValidateLibraryTags:
    @pytest.mark.unit
    @pytest.mark.mocked
    def test_validate_library_tags_calls_resolve_then_workflow(self) -> None:
        service = _make_service()
        library_id = "libraries/lib1"
        expected = {
            "files_checked": 10,
            "incomplete_files": 2,
            "repaired_files": 2,
        }

        with (
            patch(
                "nomarr.services.domain.library_svc.scan.resolve_library_for_scan",
            ) as mock_resolve_library_for_scan,
            patch(
                "nomarr.services.domain.library_svc.scan.validate_library_tags_workflow",
                return_value=expected,
            ) as mock_validate_library_tags_workflow,
        ):
            result = service.validate_library_tags(library_id)

        mock_resolve_library_for_scan.assert_called_once_with(service.db, library_id)
        mock_validate_library_tags_workflow.assert_called_once_with(
            db=service.db,
            models_dir=service.cfg.models_dir,
            library_id=library_id,
            namespace=service.cfg.namespace,
            auto_repair=True,
        )
        assert result == expected

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_validate_library_tags_propagates_library_not_found(self) -> None:
        service = _make_service()
        library_id = "libraries/missing"

        with (
            patch(
                "nomarr.services.domain.library_svc.scan.resolve_library_for_scan",
                side_effect=ValueError("not found"),
            ) as mock_resolve_library_for_scan,
            patch(
                "nomarr.services.domain.library_svc.scan.validate_library_tags_workflow",
            ) as mock_validate_library_tags_workflow,
            pytest.raises(ValueError, match="not found"),
        ):
            service.validate_library_tags(library_id)

        mock_resolve_library_for_scan.assert_called_once_with(service.db, library_id)
        mock_validate_library_tags_workflow.assert_not_called()
