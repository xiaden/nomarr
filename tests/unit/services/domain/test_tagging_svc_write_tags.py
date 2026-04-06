"""Tests for BTS-backed write-tags behavior in ``nomarr.services.domain.tagging_svc``."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers import ManagedTask
from nomarr.helpers.dto.library_dto import WriteTagsResult
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig


def _make_service(*, db: MagicMock | None = None, bts: MagicMock | None = None) -> TaggingService:
    """Build a minimal TaggingService for write-tags tests."""
    return TaggingService(
        database=db or MagicMock(),
        cfg=TaggingServiceConfig(
            models_dir="models",
            namespace="nom",
            version_tag_key="nom:version",
        ),
        bts=bts or MagicMock(),
        config_service=MagicMock(),
    )


class TestStartWriteTagsBackground:
    """Tests for BTS-backed write-tags dispatch."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_write_tags_background_registers_task(self) -> None:
        """Service should register a ManagedTask with the expected task id."""
        mock_bts = MagicMock()
        mock_bts.start_task.return_value = "write_tags:lib1"
        service = _make_service(bts=mock_bts)
        with patch.object(
            service,
            "write_tags_to_files",
            return_value=SimpleNamespace(remaining=0),
        ) as mock_write_tags:
            task_id = service.start_write_tags_background("lib1", threading.Event())

            assert task_id == "write_tags:lib1"
            mock_bts.start_task.assert_called_once()
            managed_task = mock_bts.start_task.call_args.args[0]
            assert isinstance(managed_task, ManagedTask)
            assert managed_task.task_id == "write_tags:lib1"

            managed_task.fn()

            mock_write_tags.assert_called_once_with("lib1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_write_tags_background_cancel_exits_loop(self) -> None:
        """Pre-set cancellation should prevent the inner task loop from writing tags."""
        mock_bts = MagicMock()
        mock_bts.start_task.return_value = "write_tags:lib1"
        service = _make_service(bts=mock_bts)
        with patch.object(
            service,
            "write_tags_to_files",
            return_value=SimpleNamespace(remaining=5),
        ) as mock_write_tags:
            stop_event = threading.Event()
            stop_event.set()

            service.start_write_tags_background("lib1", stop_event)

            managed_task = mock_bts.start_task.call_args.args[0]
            assert isinstance(managed_task, ManagedTask)
            assert managed_task.stop_event is stop_event

            managed_task.fn()

            mock_write_tags.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_write_tags_background_wires_on_complete(self) -> None:
        """on_complete callback should be forwarded to ManagedTask."""
        mock_bts = MagicMock()
        mock_bts.start_task.return_value = "write_tags:lib1"
        service = _make_service(bts=mock_bts)
        my_callback = MagicMock()

        service.start_write_tags_background("lib1", threading.Event(), on_complete=my_callback)

        managed_task = mock_bts.start_task.call_args.args[0]
        assert managed_task.on_complete is my_callback

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_write_tags_background_loops_until_remaining_zero(self) -> None:
        """Task loop should keep calling write_tags_to_files until remaining==0."""
        mock_bts = MagicMock()
        mock_bts.start_task.return_value = "write_tags:lib1"
        service = _make_service(bts=mock_bts)
        write_results = [
            SimpleNamespace(remaining=5),
            SimpleNamespace(remaining=2),
            SimpleNamespace(remaining=0),
        ]
        with patch.object(service, "write_tags_to_files", side_effect=write_results) as mock_write_tags:
            service.start_write_tags_background("lib1", threading.Event())

            managed_task = mock_bts.start_task.call_args.args[0]
            managed_task.fn()

            assert mock_write_tags.call_count == 3


class TestGetReconcileStatus:
    """Tests for reconcile status polling."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_in_progress_true_when_running(self) -> None:
        """Running BTS state should surface as in_progress=True."""
        mock_db = MagicMock()
        mock_db.libraries.get_library.return_value = {"_id": "lib1"}
        mock_db.library_files.count_files_needing_reconciliation.return_value = 4
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {"status": "running"}
        service = _make_service(db=mock_db, bts=mock_bts)

        result = service.get_reconcile_status("lib1")

        assert result == {"pending_count": 4, "in_progress": True}
        mock_bts.get_task_status.assert_called_once_with("write_tags:lib1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_in_progress_false_when_idle(self) -> None:
        """Missing BTS task state should surface as in_progress=False."""
        mock_db = MagicMock()
        mock_db.libraries.get_library.return_value = {"_id": "lib1"}
        mock_db.library_files.count_files_needing_reconciliation.return_value = 2
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = None
        service = _make_service(db=mock_db, bts=mock_bts)

        result = service.get_reconcile_status("lib1")

        assert result == {"pending_count": 2, "in_progress": False}
        mock_bts.get_task_status.assert_called_once_with("write_tags:lib1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_raises_for_unknown_library(self) -> None:
        """Unknown libraries should raise ValueError before BTS status is queried."""
        mock_db = MagicMock()
        mock_db.libraries.get_library.return_value = None
        mock_bts = MagicMock()
        service = _make_service(db=mock_db, bts=mock_bts)

        with pytest.raises(ValueError, match="Library not found: lib1"):
            service.get_reconcile_status("lib1")

        mock_bts.get_task_status.assert_not_called()


class TestWriteTagsToFiles:
    """Tests for direct write-tags batch processing."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_tags_to_files_raises_for_unknown_library(self) -> None:
        """Unknown libraries should raise ValueError before claiming files."""
        mock_db = MagicMock()
        mock_db.libraries.get_library.return_value = None
        service = _make_service(db=mock_db)

        with pytest.raises(ValueError, match="Library not found: lib1"):
            service.write_tags_to_files("lib1")

        mock_db.library_files.claim_files_for_reconciliation.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_tags_to_files_happy_path(self) -> None:
        """Successful writes should increment processed and leave failed at zero."""
        mock_db = MagicMock()
        mock_db.libraries.get_library.return_value = {"file_write_mode": "full"}
        mock_db.meta.get.return_value = "calibration-v1"
        mock_db.library_files.claim_files_for_reconciliation.return_value = [
            {"_key": "file1"},
            {"_key": "file2"},
        ]
        mock_db.library_files.count_files_needing_reconciliation.return_value = 0
        service = _make_service(db=mock_db)

        with patch(
            "nomarr.services.domain.tagging_svc.write_file_tags_workflow",
            side_effect=[
                SimpleNamespace(success=True),
                SimpleNamespace(success=True),
            ],
        ) as mock_workflow:
            result = service.write_tags_to_files("lib1")

        assert result == WriteTagsResult(processed=2, remaining=0, failed=0)
        assert mock_workflow.call_count == 2
        mock_db.library_files.release_claim.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_tags_to_files_partial_failure(self) -> None:
        """Non-external workflow failures should increment failed without releasing claims."""
        mock_db = MagicMock()
        mock_db.libraries.get_library.return_value = {"file_write_mode": "minimal"}
        mock_db.meta.get.return_value = "calibration-v1"
        mock_db.library_files.claim_files_for_reconciliation.return_value = [
            {"_key": "file1"},
            {"_key": "file2"},
        ]
        mock_db.library_files.count_files_needing_reconciliation.return_value = 0
        service = _make_service(db=mock_db)

        with patch(
            "nomarr.services.domain.tagging_svc.write_file_tags_workflow",
            side_effect=[
                SimpleNamespace(success=True),
                SimpleNamespace(success=False, error="write_error"),
            ],
        ):
            result = service.write_tags_to_files("lib1")

        assert result == WriteTagsResult(processed=1, remaining=0, failed=1)
        mock_db.library_files.release_claim.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_tags_to_files_externally_modified_file(self) -> None:
        """Externally modified files should release their claim and not count as failed."""
        mock_db = MagicMock()
        mock_db.libraries.get_library.return_value = {"file_write_mode": "full"}
        mock_db.meta.get.return_value = None
        mock_db.library_files.claim_files_for_reconciliation.return_value = [{"_key": "file1"}]
        mock_db.library_files.count_files_needing_reconciliation.return_value = 0
        service = _make_service(db=mock_db)

        with patch(
            "nomarr.services.domain.tagging_svc.write_file_tags_workflow",
            return_value=SimpleNamespace(success=False, error="file_modified_externally"),
        ):
            result = service.write_tags_to_files("lib1")

        assert result == WriteTagsResult(processed=0, remaining=0, failed=0)
        mock_db.library_files.release_claim.assert_called_once_with("file1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_tags_to_files_exception_releases_claim(self) -> None:
        """Workflow exceptions should count as failures and release the file claim."""
        mock_db = MagicMock()
        mock_db.libraries.get_library.return_value = {"file_write_mode": "full"}
        mock_db.meta.get.return_value = "calibration-v1"
        mock_db.library_files.claim_files_for_reconciliation.return_value = [{"_key": "file1"}]
        mock_db.library_files.count_files_needing_reconciliation.return_value = 0
        service = _make_service(db=mock_db)

        with patch(
            "nomarr.services.domain.tagging_svc.write_file_tags_workflow",
            side_effect=RuntimeError("boom"),
        ):
            result = service.write_tags_to_files("lib1")

        assert result == WriteTagsResult(processed=0, remaining=0, failed=1)
        mock_db.library_files.release_claim.assert_called_once_with("file1")
