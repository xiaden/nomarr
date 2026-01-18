"""
Unit tests for LibraryService scan_targets() Phase 3 implementation.

Tests verify:
- scan_targets() validates inputs correctly
- start_scan_for_library() delegates to scan_targets() with correct target
- Validation catches empty targets, duplicate libraries, missing libraries
"""

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dto.library_dto import LibraryDict, ScanTarget, StartScanResult
from nomarr.services.domain.library_svc import LibraryService


class TestScanTargetsValidation:
    """Test scan_targets() input validation."""

    def test_rejects_empty_targets_list(self):
        """scan_targets() should reject empty targets list."""
        mock_db = MagicMock()
        mock_background_tasks = MagicMock()
        mock_cfg = MagicMock()

        service = LibraryService(db=mock_db, cfg=mock_cfg, background_tasks=mock_background_tasks)

        with pytest.raises(ValueError, match="targets list is empty"):
            service.scan_targets([])

    def test_rejects_duplicate_library_ids(self):
        """scan_targets() should reject multiple targets for same library."""
        mock_db = MagicMock()
        mock_background_tasks = MagicMock()
        mock_cfg = MagicMock()

        service = LibraryService(db=mock_db, cfg=mock_cfg, background_tasks=mock_background_tasks)

        targets = [
            ScanTarget(library_id="lib1", folder_path="Rock"),
            ScanTarget(library_id="lib1", folder_path="Jazz"),
        ]

        with pytest.raises(ValueError, match="multiple targets reference the same library"):
            service.scan_targets(targets)

    def test_rejects_nonexistent_library(self):
        """scan_targets() should reject if library not found."""
        mock_db = MagicMock()
        mock_background_tasks = MagicMock()
        mock_cfg = MagicMock()

        # Mock _get_library_or_error to raise ValueError
        service = LibraryService(db=mock_db, cfg=mock_cfg, background_tasks=mock_background_tasks)
        service._get_library_or_error = MagicMock(side_effect=ValueError("Library not found: bad_lib"))  # type: ignore[method-assign]

        targets = [ScanTarget(library_id="bad_lib", folder_path="")]

        with pytest.raises(ValueError, match="Library not found"):
            service.scan_targets(targets)

    def test_accepts_valid_single_target(self, monkeypatch):
        """scan_targets() should accept valid single target and delegate to workflow."""
        mock_db = MagicMock()
        mock_background_tasks = MagicMock()
        mock_cfg = MagicMock()

        service = LibraryService(db=mock_db, cfg=mock_cfg, background_tasks=mock_background_tasks)
        service._get_library_or_error = MagicMock(  # type: ignore[method-assign]
            return_value=LibraryDict(
                _id="libraries/lib1",
                _key="lib1",
                _rev="_abc123",
                name="Test Library",
                root_path="/music",
                is_enabled=True,
                is_default=False,
                created_at=1000000,
                updated_at=1000000,
            )
        )

        # Mock start_scan_workflow
        mock_start_scan = MagicMock(
            return_value=StartScanResult(
                files_discovered=100,
                files_queued=50,
                files_skipped=30,
                files_removed=20,
                job_ids=["task_123"],
            )
        )

        # Patch where start_scan_workflow is imported and used
        monkeypatch.setattr(
            "nomarr.workflows.library.start_scan_wf.start_scan_workflow",
            mock_start_scan,
        )

        targets = [ScanTarget(library_id="lib1", folder_path="")]
        result = service.scan_targets(targets)

        assert result.files_discovered == 100
        assert result.job_ids == ["task_123"]

        # Verify workflow called with correct parameters
        mock_start_scan.assert_called_once()
        call_kwargs = mock_start_scan.call_args.kwargs
        assert call_kwargs["db"] is mock_db
        assert call_kwargs["background_tasks"] is mock_background_tasks
        assert call_kwargs["library_id"] == "lib1"
        assert call_kwargs["scan_targets"] == targets
        assert call_kwargs["batch_size"] == 200

    def test_accepts_valid_multiple_targets(self, monkeypatch):
        """scan_targets() should accept multiple targets for different libraries."""
        mock_db = MagicMock()
        mock_background_tasks = MagicMock()
        mock_cfg = MagicMock()

        service = LibraryService(db=mock_db, cfg=mock_cfg, background_tasks=mock_background_tasks)

        # Mock _get_library_or_error to return different libraries
        def mock_get_library(library_id):
            return LibraryDict(
                _id=f"libraries/{library_id}",
                _key=library_id,
                _rev="_abc123",
                name=f"Library {library_id}",
                root_path=f"/music/{library_id}",
                is_enabled=True,
                is_default=False,
                created_at=1000000,
                updated_at=1000000,
            )

        service._get_library_or_error = MagicMock(side_effect=mock_get_library)  # type: ignore[method-assign]

        # Mock start_scan_workflow
        mock_start_scan = MagicMock(
            return_value=StartScanResult(
                files_discovered=200,
                files_queued=100,
                files_skipped=50,
                files_removed=50,
                job_ids=["task_456"],
            )
        )

        # Patch where start_scan_workflow is imported and used
        monkeypatch.setattr(
            "nomarr.workflows.library.start_scan_wf.start_scan_workflow",
            mock_start_scan,
        )

        targets = [
            ScanTarget(library_id="lib1", folder_path="Rock"),
            ScanTarget(library_id="lib2", folder_path="Jazz"),
        ]
        result = service.scan_targets(targets)

        assert result.files_discovered == 200

        # Verify both libraries were validated
        assert service._get_library_or_error.call_count == 2


class TestStartScanForLibraryDelegation:
    """Test start_scan_for_library() delegates to scan_targets()."""

    def test_delegates_to_scan_targets_with_full_scan_target(self, monkeypatch):
        """start_scan_for_library() should create full scan target and delegate."""
        mock_db = MagicMock()
        mock_background_tasks = MagicMock()
        mock_cfg = MagicMock()

        service = LibraryService(db=mock_db, cfg=mock_cfg, background_tasks=mock_background_tasks)

        # Mock scan_targets
        mock_scan_targets = MagicMock(
            return_value=StartScanResult(
                files_discovered=150,
                files_queued=75,
                files_skipped=50,
                files_removed=25,
                job_ids=["task_789"],
            )
        )

        service.scan_targets = mock_scan_targets  # type: ignore[method-assign]

        result = service.start_scan_for_library("lib1")

        assert result.files_discovered == 150
        assert result.job_ids == ["task_789"]

        # Verify scan_targets called with full scan target (empty folder_path)
        mock_scan_targets.assert_called_once()
        call_args = mock_scan_targets.call_args
        targets = call_args[0][0]

        assert len(targets) == 1
        assert targets[0].library_id == "lib1"
        assert targets[0].folder_path == ""  # Full scan
