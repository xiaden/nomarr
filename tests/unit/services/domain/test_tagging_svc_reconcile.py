"""Tests for BTS-backed reconcile behavior in ``nomarr.services.domain.tagging_svc``."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers import ManagedTask
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig


def _make_service(*, db: MagicMock | None = None, bts: MagicMock | None = None) -> TaggingService:
    """Build a minimal TaggingService for reconcile tests."""
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
            "reconcile_library",
            return_value=SimpleNamespace(remaining=0),
        ) as mock_reconcile:
            task_id = service.start_write_tags_background("lib1", threading.Event())

            assert task_id == "write_tags:lib1"
            mock_bts.start_task.assert_called_once()
            managed_task = mock_bts.start_task.call_args.args[0]
            assert isinstance(managed_task, ManagedTask)
            assert managed_task.task_id == "write_tags:lib1"

            managed_task.fn()

            mock_reconcile.assert_called_once_with("lib1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_write_tags_background_cancel_exits_loop(self) -> None:
        """Pre-set cancellation should prevent the inner task loop from reconciling."""
        mock_bts = MagicMock()
        mock_bts.start_task.return_value = "write_tags:lib1"
        service = _make_service(bts=mock_bts)
        with patch.object(
            service,
            "reconcile_library",
            return_value=SimpleNamespace(remaining=5),
        ) as mock_reconcile:
            stop_event = threading.Event()
            stop_event.set()

            service.start_write_tags_background("lib1", stop_event)

            managed_task = mock_bts.start_task.call_args.args[0]
            assert isinstance(managed_task, ManagedTask)
            assert managed_task.stop_event is stop_event

            managed_task.fn()

            mock_reconcile.assert_not_called()

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
        """Task loop should keep calling reconcile_library until remaining==0."""
        mock_bts = MagicMock()
        mock_bts.start_task.return_value = "write_tags:lib1"
        service = _make_service(bts=mock_bts)
        reconcile_results = [
            SimpleNamespace(remaining=5),
            SimpleNamespace(remaining=2),
            SimpleNamespace(remaining=0),
        ]
        with patch.object(service, "reconcile_library", side_effect=reconcile_results) as mock_reconcile:
            service.start_write_tags_background("lib1", threading.Event())

            managed_task = mock_bts.start_task.call_args.args[0]
            managed_task.fn()

            assert mock_reconcile.call_count == 3


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
