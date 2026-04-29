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
    def test_get_status_aggregate_returns_configured(self) -> None:
        """Aggregate status should return configured=True when library root is set."""
        service = _make_service()
        result = service.get_status()

        assert result.configured is True

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_status_library_scan_status_reflects_pipeline_state(self) -> None:
        """Per-library scan_status should come from pipeline state."""
        service = _make_service()
        scan_state = {
            "files_processed": 5,
            "files_total": 10,
            "error": None,
            "completed_at": None,
        }

        with (
            patch("nomarr.services.domain.library_svc.scan.resolve_library_for_scan"),
            patch(
                "nomarr.services.domain.library_svc.scan.get_scan_state",
                return_value=scan_state,
            ),
            patch(
                "nomarr.services.domain.library_svc.scan.get_pipeline_state",
                return_value="scanning",
            ),
        ):
            result = service.get_status("libraries/lib1")

        assert result.scan_status == "scanning"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_status_library_idle_pipeline_state_returns_idle_scan_status(self) -> None:
        """Per-library scan_status should be idle when pipeline state is idle."""
        service = _make_service()
        scan_state = {
            "files_processed": 0,
            "files_total": 0,
            "error": None,
            "completed_at": None,
        }

        with (
            patch("nomarr.services.domain.library_svc.scan.resolve_library_for_scan"),
            patch(
                "nomarr.services.domain.library_svc.scan.get_scan_state",
                return_value=scan_state,
            ),
            patch(
                "nomarr.services.domain.library_svc.scan.get_pipeline_state",
                return_value="idle",
            ),
        ):
            result = service.get_status("libraries/lib1")

        assert result.scan_status == "idle"

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
