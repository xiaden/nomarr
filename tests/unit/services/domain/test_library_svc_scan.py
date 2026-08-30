"""Tests for ``nomarr.services.domain.library_svc.scan`` mixin behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers import ManagedTask
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryPipelineState, LibraryScan
from nomarr.helpers.exceptions import LibraryAlreadyScanningError
from nomarr.services.domain.library_svc import LibraryService, LibraryServiceConfig
from nomarr.services.domain.library_svc.task_ids import library_task_id

if TYPE_CHECKING:
    import functools


def _make_library(*, name: str = "Rock Library") -> Library:
    """Build a domain ``Library`` (natural identity) fixture."""
    return Library(name=name, root_path="/music")


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


def _make_pipeline_state(scan_state: str) -> LibraryPipelineState:
    """Build a canonical ``LibraryPipelineState`` with the given scan axis."""
    return LibraryPipelineState(
        scan_state=scan_state,
        ml_state="not_ML_processed",
        calibration_state="not_calibrated",
        tag_write_state="not_written",
    )


class TestScanDispatch:
    """Tests for ManagedTask-backed scan dispatch methods."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_quick_scan_registers_managed_task(self) -> None:
        """Quick scan should register a ManagedTask with the deterministic natural task id."""
        mock_bts = MagicMock()
        service = _make_service(background_tasks=mock_bts)
        library = _make_library()
        expected_task_id = library_task_id(library, "scan")

        with (
            patch("nomarr.services.domain.library_svc.scan.scan_setup_workflow") as mock_scan_setup,
            patch(
                "nomarr.services.domain.library_svc.scan.on_scan_complete_pipeline_hook",
            ) as mock_on_complete_hook,
        ):
            result = service.start_quick_scan(library)

            mock_scan_setup.assert_called_once_with(service.db, library, scan_type="quick")
            mock_bts.start_task.assert_called_once()
            managed_task = mock_bts.start_task.call_args.args[0]
            assert isinstance(managed_task, ManagedTask)
            assert managed_task.task_id == expected_task_id
            assert cast("functools.partial", managed_task.fn).keywords["stop_event"] is managed_task.stop_event
            assert managed_task.on_complete is not None
            managed_task.on_complete()
            mock_on_complete_hook.assert_called_once_with(service.db, library)
        assert result.job_ids == [expected_task_id]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_full_scan_registers_managed_task(self) -> None:
        """Full scan should register a ManagedTask with the deterministic natural task id."""
        mock_bts = MagicMock()
        service = _make_service(background_tasks=mock_bts)
        library = _make_library()
        expected_task_id = library_task_id(library, "scan")

        with (
            patch("nomarr.services.domain.library_svc.scan.scan_setup_workflow") as mock_scan_setup,
            patch(
                "nomarr.services.domain.library_svc.scan.on_scan_complete_pipeline_hook",
            ) as mock_on_complete_hook,
        ):
            result = service.start_full_scan(library)

            mock_scan_setup.assert_called_once_with(service.db, library, scan_type="full")
            mock_bts.start_task.assert_called_once()
            managed_task = mock_bts.start_task.call_args.args[0]
            assert isinstance(managed_task, ManagedTask)
            assert managed_task.task_id == expected_task_id
            assert cast("functools.partial", managed_task.fn).keywords["stop_event"] is managed_task.stop_event
            assert managed_task.on_complete is not None
            managed_task.on_complete()
            mock_on_complete_hook.assert_called_once_with(service.db, library)
        assert result.job_ids == [expected_task_id]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_cancel_scan_signals_library_task(self) -> None:
        """Cancelling a scan must target the same natural task id used by start/status."""
        mock_bts = MagicMock()
        mock_bts.cancel_task.return_value = True
        service = _make_service(background_tasks=mock_bts)
        library = _make_library()
        expected_task_id = library_task_id(library, "scan")

        assert service.cancel_scan(library) is True
        mock_bts.cancel_task.assert_called_once_with(expected_task_id)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_and_cancel_resolve_to_same_task_id(self) -> None:
        """start_quick_scan and cancel_scan must derive the identical escaped task key."""
        mock_bts = MagicMock()
        mock_bts.cancel_task.return_value = True
        service = _make_service(background_tasks=mock_bts)
        library = _make_library(name="Rock/Acoustic & Chill")
        expected_task_id = library_task_id(library, "scan")

        with (
            patch("nomarr.services.domain.library_svc.scan.scan_setup_workflow"),
            patch("nomarr.services.domain.library_svc.scan.on_scan_complete_pipeline_hook"),
        ):
            started = service.start_quick_scan(library)
            cancelled = service.cancel_scan(library)

        assert started.job_ids == [expected_task_id]
        mock_bts.cancel_task.assert_called_once_with(expected_task_id)
        assert cancelled is True

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_cancel_scan_without_library_returns_false(self) -> None:
        service = _make_service()

        assert service.cancel_scan() is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_cancel_scan_without_background_tasks_returns_false(self) -> None:
        service = LibraryService(
            cfg=LibraryServiceConfig(
                models_dir="models",
                namespace="nom",
                tagger_version="tagger-v1",
                library_root="/music",
            ),
            db=MagicMock(),
            background_tasks=None,
        )

        assert service.cancel_scan(_make_library()) is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_cancel_scan_requires_configured_library(self) -> None:
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

        with pytest.raises(ValueError, match="Library scanning not configured"):
            service.cancel_scan(_make_library())


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
        """Per-library scan_status should come from the domain pipeline state."""
        service = _make_service()
        library = _make_library()
        scan_state = LibraryScan(
            scan_type="quick",
            status="in_progress",
            started_at=0,
            files_processed=5,
            files_found=10,
        )
        pipeline_state = _make_pipeline_state(scan_state="scanning")

        with (
            patch("nomarr.services.domain.library_svc.scan.resolve_library_for_scan"),
            patch(
                "nomarr.services.domain.library_svc.scan.get_scan_state",
                return_value=scan_state,
            ),
            patch(
                "nomarr.services.domain.library_svc.scan.get_pipeline_state",
                return_value=pipeline_state,
            ),
        ):
            result = service.get_status(library)

        assert result.scan_status == "scanning"
        assert result.scan_progress == 5
        assert result.scan_total == 10

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_status_library_idle_pipeline_state_returns_idle_scan_status(self) -> None:
        """Per-library scan_status should be idle when pipeline state is not scanning."""
        service = _make_service()
        library = _make_library()
        scan_state = LibraryScan(
            scan_type="quick",
            status="in_progress",
            started_at=0,
            files_processed=0,
            files_found=0,
        )
        pipeline_state = _make_pipeline_state(scan_state="not_scanned")

        with (
            patch("nomarr.services.domain.library_svc.scan.resolve_library_for_scan"),
            patch(
                "nomarr.services.domain.library_svc.scan.get_scan_state",
                return_value=scan_state,
            ),
            patch(
                "nomarr.services.domain.library_svc.scan.get_pipeline_state",
                return_value=pipeline_state,
            ),
        ):
            result = service.get_status(library)

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
                "library_id": "Rock Library",
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
        library = _make_library()
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
            result = service.validate_library_tags(library)

        mock_resolve_library_for_scan.assert_called_once_with(service.db, library)
        mock_validate_library_tags_workflow.assert_called_once_with(
            db=service.db,
            models_dir=service.cfg.models_dir,
            library=library,
            namespace=service.cfg.namespace,
            auto_repair=True,
        )
        assert result == expected

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_validate_library_tags_propagates_library_not_found(self) -> None:
        service = _make_service()
        library = _make_library()

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
            service.validate_library_tags(library)

        mock_resolve_library_for_scan.assert_called_once_with(service.db, library)
        mock_validate_library_tags_workflow.assert_not_called()


class TestRepairLibraryTags:
    """Tests for tag-repair admission ordering and side-effect safety."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_repair_library_tags_admits_before_mutating_state(self) -> None:
        """Tag repair must claim the scan row before transitioning song state."""
        mock_bts = MagicMock()
        service = _make_service(background_tasks=mock_bts)
        library = _make_library()
        expected_task_id = library_task_id(library, "scan")

        with (
            patch("nomarr.services.domain.library_svc.scan.resolve_library_for_scan") as mock_resolve,
            patch("nomarr.services.domain.library_svc.scan.scan_setup_workflow") as mock_admit,
            patch(
                "nomarr.services.domain.library_svc.scan.bulk_set_not_hydrated",
                return_value=42,
            ) as mock_bulk,
            patch("nomarr.services.domain.library_svc.scan.on_scan_complete_pipeline_hook"),
        ):
            parent = MagicMock()
            parent.attach_mock(mock_resolve, "resolve")
            parent.attach_mock(mock_admit, "admit")
            parent.attach_mock(mock_bulk, "bulk")

            result = service.repair_library_tags(library)

        order = [call[0] for call in parent.method_calls]
        assert order.index("admit") < order.index("bulk")

        mock_resolve.assert_called_once_with(service.db, library)
        mock_admit.assert_called_once_with(service.db, library, scan_type="full")
        mock_bulk.assert_called_once_with(service.db, library)
        mock_bts.start_task.assert_called_once()
        managed_task = mock_bts.start_task.call_args.args[0]
        assert isinstance(managed_task, ManagedTask)
        # The repair path must keep the ML pipeline hook suppressed.
        assert cast("functools.partial", managed_task.fn).keywords["skip_validation_autorepair"] is True
        assert result.files_queued == 42
        assert result.job_ids == [expected_task_id]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_repair_library_tags_rejected_scan_is_side_effect_free(self) -> None:
        """A rejected repair request must not mutate any song hydration state."""
        mock_bts = MagicMock()
        service = _make_service(background_tasks=mock_bts)
        library = _make_library()

        with (
            patch("nomarr.services.domain.library_svc.scan.resolve_library_for_scan"),
            patch(
                "nomarr.services.domain.library_svc.scan.scan_setup_workflow",
                side_effect=LibraryAlreadyScanningError("already scanning"),
            ),
            patch("nomarr.services.domain.library_svc.scan.bulk_set_not_hydrated") as mock_bulk,
            pytest.raises(LibraryAlreadyScanningError, match="already scanning"),
        ):
            service.repair_library_tags(library)

        mock_bulk.assert_not_called()
        mock_bts.start_task.assert_not_called()
