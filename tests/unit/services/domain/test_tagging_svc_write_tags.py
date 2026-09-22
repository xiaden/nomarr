"""Tests for BTS-backed write-tags behavior in ``nomarr.services.domain.tagging_svc``."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar, Literal
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers import ManagedTask
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
from nomarr.helpers.dto.library_dto import WriteOutcome, WriteTagsResult
from nomarr.helpers.exceptions import TaskCancelledError
from nomarr.helpers.fs_contract import FsFact
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig
from nomarr.services.domain.tagging_svc.write import _is_retryable

if TYPE_CHECKING:
    from nomarr.helpers.dto.tag_curation_dto import CommitResult


def _make_library(name: str = "lib1", file_write_mode: Literal["none", "minimal", "full"] = "full") -> Library:
    """Build a domain ``Library`` (natural identity) for write-tags tests."""
    return Library(
        name=name,
        root_path="/music",
        library_uuid=f"uuid-{name}",
        file_write_mode=file_write_mode,
    )


def _song(*, normalized_path: str = "song.mp3") -> Song:
    """Build a semantic ``Song`` (natural identity) for write-tags tests."""
    return Song(
        path=f"/music/{normalized_path}",
        normalized_path=normalized_path,
        file_size=100,
        modified_time=1000,
        duration_seconds=None,
        chromaprint=None,
        needs_tagging=False,
        is_valid=True,
        tagged=False,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=1000,
    )


def _identity(normalized_path: str = "song.mp3") -> SongIdentity:
    """Build the semantic locator matching ``_song``/``_make_library``."""
    return SongIdentity(
        library=LibraryIdentity(library_uuid="uuid-lib1", name="lib1", root_path="/music"),
        normalized_path=normalized_path,
    )


def _candidate(normalized_path: str = "song.mp3") -> SongStateCandidate:
    """Build a real typed reconciliation candidate."""
    return SongStateCandidate(
        identity=_identity(normalized_path),
        song=_song(normalized_path=normalized_path),
        states=("not_written",),
    )


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
        library = _make_library()
        with patch.object(
            service,
            "_write_admitted_tags_to_files",
            return_value=SimpleNamespace(remaining=0),
        ) as mock_write_tags:
            task_id = service.start_write_tags_background(library, threading.Event())

            assert task_id == "write_tags:lib1"
            mock_bts.start_task.assert_called_once()
            managed_task = mock_bts.start_task.call_args.args[0]
            assert isinstance(managed_task, ManagedTask)
            assert managed_task.task_id == "write_tags:lib1"

            managed_task.fn()

            mock_write_tags.assert_called_once_with(
                library, exclude_locators=set(), retry_counts={}, requested_mode="none"
            )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_write_tags_background_propagates_requested_mode(self) -> None:
        """The normalized mode reaches the admitted batch seam."""
        mock_bts = MagicMock()
        mock_bts.start_task.return_value = "write_tags:lib1"
        service = _make_service(bts=mock_bts)
        with patch.object(
            service,
            "_write_admitted_tags_to_files",
            return_value=SimpleNamespace(remaining=0),
        ) as mock_write_tags:
            service.start_write_tags_background(_make_library(), threading.Event(), requested_mode="database")
            managed_task = mock_bts.start_task.call_args.args[0]
            managed_task.fn()

        assert mock_write_tags.call_args.kwargs["requested_mode"] == "database"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_start_write_tags_background_cancel_exits_loop(self) -> None:
        """Pre-set cancellation should prevent the inner task loop from writing tags."""
        mock_bts = MagicMock()
        mock_bts.start_task.return_value = "write_tags:lib1"
        service = _make_service(bts=mock_bts)
        with patch.object(
            service,
            "_write_admitted_tags_to_files",
            return_value=SimpleNamespace(remaining=5),
        ) as mock_write_tags:
            stop_event = threading.Event()
            stop_event.set()

            service.start_write_tags_background(_make_library(), stop_event)

            managed_task = mock_bts.start_task.call_args.args[0]
            assert isinstance(managed_task, ManagedTask)
            assert managed_task.stop_event is stop_event

            with pytest.raises(TaskCancelledError):
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

        service.start_write_tags_background(_make_library(), threading.Event(), on_complete=my_callback)

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
        with (
            patch.object(service, "_write_admitted_tags_to_files", side_effect=write_results) as mock_write_tags,
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=5,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write._INTER_ATTEMPT_DELAY_SECONDS",
                0.0,
            ),
        ):
            service.start_write_tags_background(_make_library(), threading.Event(), requested_mode="files")

            managed_task = mock_bts.start_task.call_args.args[0]
            managed_task.fn()

            assert mock_write_tags.call_count == 3
            assert all(call.kwargs["requested_mode"] == "files" for call in mock_write_tags.call_args_list)


class TestGetReconcileStatus:
    """Tests for reconcile status polling."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_in_progress_true_when_running(self) -> None:
        """Running BTS state should surface as in_progress=True."""
        mock_db = MagicMock()
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {"status": "running"}
        service = _make_service(db=mock_db, bts=mock_bts)

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=4,
            ),
        ):
            result = service.get_reconcile_status(_make_library())

        assert result["pending_count"] == 4
        assert result["failed_count"] == 0
        assert result["in_progress"] is True
        assert result["outcome"] == "active"
        assert result["message_code"] == "TAG_WRITE_ACTIVE"
        assert result["requested_mode"] == "none"
        assert result["resumable"] is True
        assert result["recovery_action"] == "retry"
        mock_bts.get_task_status.assert_called_once_with("write_tags:lib1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_preserves_requested_mode_from_result(self) -> None:
        """Terminal status carries the selected recovery mode through the boundary."""
        mock_db = MagicMock()
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {
            "status": "complete",
            "result": WriteTagsResult(processed=1, remaining=0, failed=0, outcome="complete", requested_mode="files"),
        }
        service = _make_service(db=mock_db, bts=mock_bts)

        with patch(
            "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
            return_value=0,
        ):
            result = service.get_reconcile_status(_make_library())

        assert result["outcome"] == "written"
        assert result["requested_mode"] == "files"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_preserves_typed_terminal_status_facts(self) -> None:
        """Existing producer facts override conservative compatibility defaults."""
        mock_db = MagicMock()
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {
            "status": "complete",
            "requested_mode": "database",
            "outcome": "replacement",
            "selected_run_counts": {"selected": 2, "remaining": 1, "unavailable": 1},
            "evidence_class": "fingerprint_different",
            "resumable": True,
            "recovery_action": "replacement_reimport_requeue",
            "message_code": "TAG_WRITE_REPLACEMENT",
            "result": WriteTagsResult(processed=1, remaining=1, failed=0, outcome="partial"),
        }
        service = _make_service(db=mock_db, bts=mock_bts)

        with patch(
            "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
            return_value=1,
        ):
            result = service.get_reconcile_status(_make_library())

        assert result["requested_mode"] == "database"
        assert result["outcome"] == "replacement"
        assert result["selected_run_counts"] == {"selected": 2, "remaining": 1, "unavailable": 1}
        assert result["evidence_class"] == "fingerprint_different"
        assert result["recovery_action"] == "replacement_reimport_requeue"
        assert result["message_code"] == "TAG_WRITE_REPLACEMENT"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_projects_evicted_terminal_status(self) -> None:
        """Evicted BTS facts remain visible in the normalized API status."""
        mock_db = MagicMock()
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {
            "status": "complete",
            "requested_mode": "files",
            "outcome": "evicted",
            "selected_run_counts": {"selected": 3, "processed": 2, "remaining": 1},
            "evidence_class": "result_evicted",
            "resumable": True,
            "recovery_action": "refresh_status",
            "message_code": "TAG_WRITE_RESULT_EVICTED",
            "result": WriteTagsResult(processed=2, remaining=1, failed=0, outcome="partial"),
        }
        service = _make_service(db=mock_db, bts=mock_bts)

        with patch(
            "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
            return_value=1,
        ):
            result = service.get_reconcile_status(_make_library())

        assert result["outcome"] == "evicted"
        assert result["requested_mode"] == "files"
        assert result["selected_run_counts"] == {"selected": 3, "processed": 2, "remaining": 1}
        assert result["evidence_class"] == "result_evicted"
        assert result["resumable"] is True
        assert result["recovery_action"] == "refresh_status"
        assert result["message_code"] == "TAG_WRITE_RESULT_EVICTED"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_in_progress_false_when_idle(self) -> None:
        """Missing BTS task state should surface as in_progress=False."""
        mock_db = MagicMock()
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = None
        service = _make_service(db=mock_db, bts=mock_bts)

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=2,
            ),
        ):
            result = service.get_reconcile_status(_make_library())

        assert result["pending_count"] == 2
        assert result["failed_count"] == 0
        assert result["in_progress"] is False
        assert result["outcome"] == "not_written"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_exposes_completed_failures(self) -> None:
        """Completed write batches expose failures alongside pending work."""
        mock_db = MagicMock()
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {
            "status": "complete",
            "result": WriteTagsResult(processed=1, remaining=2, failed=2, outcome="partial"),
        }
        service = _make_service(db=mock_db, bts=mock_bts)

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=2,
            ),
        ):
            result = service.get_reconcile_status(_make_library())

        assert result["pending_count"] == 2
        assert result["failed_count"] == 2
        assert result["in_progress"] is False
        assert result["outcome"] == "partial"
        assert result["message_code"] == "TAG_WRITE_PARTIAL"
        assert result["selected_run_counts"] == {"processed": 1, "failed": 2, "remaining": 2}
        assert result["requested_mode"] == "none"
        assert result["resumable"] is True

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_background_task_returns_last_write_result(self) -> None:
        """BTS stores the batch result so status polling can expose failures."""
        mock_db = MagicMock()
        mock_bts = MagicMock()
        service = _make_service(db=mock_db, bts=mock_bts)
        batch_result = WriteTagsResult(processed=1, remaining=0, failed=1, outcome="complete")
        mock_bts.start_task.side_effect = lambda task: task.fn()

        with patch.object(service, "_write_admitted_tags_to_files", return_value=batch_result):
            result = service.start_write_tags_background(_make_library(), threading.Event())

        assert result == batch_result

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_no_usable_result_with_zero_pending_is_complete(self) -> None:
        """A drained library with no usable BTS result defaults conservatively to complete."""
        mock_db = MagicMock()
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = None
        service = _make_service(db=mock_db, bts=mock_bts)

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=0,
            ),
        ):
            result = service.get_reconcile_status(_make_library())

        assert result["pending_count"] == 0
        assert result["failed_count"] == 0
        assert result["in_progress"] is False
        assert result["outcome"] == "unavailable"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_completed_task_exposes_complete_outcome(self) -> None:
        """A terminal task result carrying outcome=complete is surfaced verbatim."""
        mock_db = MagicMock()
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {
            "status": "complete",
            "result": WriteTagsResult(processed=2, remaining=0, failed=0, outcome="complete"),
        }
        service = _make_service(db=mock_db, bts=mock_bts)

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=0,
            ),
        ):
            result = service.get_reconcile_status(_make_library())

        assert result["outcome"] == "written"
        assert result["message_code"] == "TAG_WRITE_COMPLETE"
        assert result["selected_run_counts"] == {"processed": 2, "failed": 0, "remaining": 0}
        assert result["requested_mode"] == "none"
        assert result["resumable"] is False
        assert result["recovery_action"] == "none"
        assert result["failed_count"] == 0
        assert result["requested_mode"] == "none"


class TestWriteTagsToFiles:
    """Tests for direct write-tags batch processing."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_tags_to_files_happy_path(self) -> None:
        """Successful writes should increment processed and leave failed at zero."""
        mock_db = MagicMock()
        mock_db.app.get_calibration_version = MagicMock(return_value="calibration-v1")
        service = _make_service(db=mock_db)
        library = _make_library(file_write_mode="full")

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.claim_files_for_reconciliation",
                return_value=[_candidate(), _candidate(normalized_path="song2.mp3")],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=0,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.release_claim",
            ) as mock_release_claim,
            patch(
                "nomarr.services.domain.tagging_svc.write.write_file_tags_workflow",
                side_effect=[
                    SimpleNamespace(success=True),
                    SimpleNamespace(success=True),
                ],
            ) as mock_workflow,
        ):
            result = service.write_tags_to_files(library)

        assert result == WriteTagsResult(processed=2, remaining=0, failed=0, outcome="complete")
        assert mock_workflow.call_count == 2
        mock_release_claim.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_tags_to_files_partial_failure(self) -> None:
        """Non-external workflow failures should increment failed and release claims."""
        mock_db = MagicMock()
        mock_db.app.get_calibration_version = MagicMock(return_value="calibration-v1")
        service = _make_service(db=mock_db)
        library = _make_library(file_write_mode="minimal")

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.claim_files_for_reconciliation",
                return_value=[_candidate(), _candidate(normalized_path="song2.mp3")],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=0,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.release_claim",
            ) as mock_release_claim,
            patch(
                "nomarr.services.domain.tagging_svc.write.write_file_tags_workflow",
                side_effect=[
                    SimpleNamespace(success=True),
                    SimpleNamespace(success=False, outcome="write_failed", fs_fact=None),
                ],
            ),
        ):
            result = service.write_tags_to_files(library)

        assert result == WriteTagsResult(processed=1, remaining=0, failed=1, outcome="complete")
        mock_release_claim.assert_called_once_with(mock_db, _identity("song2.mp3"), "reconcile:lib1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_tags_to_files_externally_modified_file(self) -> None:
        """Externally modified files should release their claim and not count as failed."""
        mock_db = MagicMock()
        mock_db.app.get_calibration_version = MagicMock(return_value=None)
        service = _make_service(db=mock_db)
        library = _make_library(file_write_mode="full")

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.claim_files_for_reconciliation",
                return_value=[_candidate()],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=0,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.release_claim",
            ) as mock_release_claim,
            patch(
                "nomarr.services.domain.tagging_svc.write.write_file_tags_workflow",
                return_value=SimpleNamespace(success=False, outcome="modified_externally", fs_fact=None),
            ),
        ):
            result = service.write_tags_to_files(library)

        assert result == WriteTagsResult(processed=0, remaining=0, failed=0, outcome="complete")
        mock_release_claim.assert_called_once_with(mock_db, _identity(), "reconcile:lib1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_tags_to_files_exception_releases_claim(self) -> None:
        """Workflow exceptions should count as failures and release the file claim."""
        mock_db = MagicMock()
        mock_db.app.get_calibration_version = MagicMock(return_value="calibration-v1")
        service = _make_service(db=mock_db)
        library = _make_library(file_write_mode="full")

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.claim_files_for_reconciliation",
                return_value=[_candidate()],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=0,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.release_claim",
            ) as mock_release_claim,
            patch(
                "nomarr.services.domain.tagging_svc.write.write_file_tags_workflow",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = service.write_tags_to_files(library)

        assert result == WriteTagsResult(processed=0, remaining=0, failed=1, outcome="complete")
        mock_release_claim.assert_called_once_with(mock_db, _identity(), "reconcile:lib1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_tags_to_files_missing_library_uuid_is_zero_work(self) -> None:
        """A library without a ``library_uuid`` cannot address songs and writes nothing."""
        mock_db = MagicMock()
        mock_db.app.get_calibration_version = MagicMock(return_value=None)
        service = _make_service(db=mock_db)
        library = Library(name="lib1", root_path="/music", library_uuid=None, file_write_mode="full")

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=0,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.write_file_tags_workflow",
            ) as mock_workflow,
        ):
            result = service.write_tags_to_files(library)

        assert result == WriteTagsResult(processed=0, remaining=0, failed=0, outcome="complete")
        # The real claim read returns no candidates for a UUID-less library.
        mock_db.library.list_songs_with_state.assert_not_called()
        mock_workflow.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_write_tags_to_files_nested_release_failure_is_tolerated(self) -> None:
        """A release failure while handling a workflow exception must not abort the batch."""
        mock_db = MagicMock()
        mock_db.app.get_calibration_version = MagicMock(return_value="calibration-v1")
        service = _make_service(db=mock_db)
        library = _make_library(file_write_mode="full")

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.claim_files_for_reconciliation",
                return_value=[_candidate()],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=0,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.release_claim",
                side_effect=RuntimeError("release boom"),
            ) as mock_release_claim,
            patch(
                "nomarr.services.domain.tagging_svc.write.write_file_tags_workflow",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = service.write_tags_to_files(library)

        assert result == WriteTagsResult(processed=0, remaining=0, failed=1, outcome="complete")
        mock_release_claim.assert_called_once_with(mock_db, _identity(), "reconcile:lib1")


class TestWriteTagsToFilesTypedClaims:
    """Regression coverage for the typed reconciliation claim contract."""

    @pytest.mark.unit
    def test_write_tags_to_files_reconciles_real_typed_claims(self) -> None:
        """Real typed claims must be re-addressed through ``candidate.identity``.

        Guards the cross-boundary break where the caller read ``song.normalized_path``
        from what the typed reconciliation returns as a ``SongStateCandidate`` (``AttributeError``).
        This exercises the real ``claim_files_for_reconciliation`` with real candidates
        (no claim mock) and asserts the workflow receives the candidate's locator.
        """
        mock_db = MagicMock()
        mock_db.app.get_calibration_version.return_value = "calibration-v1"
        mock_db.app.add_claim.return_value = True
        candidate = _candidate(normalized_path="typed/song.mp3")
        mock_db.library.list_songs_with_state.side_effect = [[candidate], []]
        service = _make_service(db=mock_db)

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=0,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.write_file_tags_workflow",
                return_value=SimpleNamespace(success=True),
            ) as mock_workflow,
        ):
            result = service.write_tags_to_files(_make_library())

        assert result == WriteTagsResult(processed=1, remaining=0, failed=0, outcome="complete")
        assert mock_workflow.call_args.kwargs["file_key"] == candidate.identity

    @pytest.mark.unit
    def test_write_tags_to_files_cancellation_releases_in_flight_claim(self) -> None:
        """A raised error mid-batch must release the in-flight typed claim and be counted.

        ``write_file_tags_workflow`` raising is handled by the loop's catch-all branch:
        the candidate's typed locator claim is released and the file is counted failed;
        the batch continues to completion. No production behavior is changed by this test.
        """
        mock_db = MagicMock()
        mock_db.app.get_calibration_version.return_value = "calibration-v1"
        mock_db.app.add_claim.return_value = True
        candidate = _candidate(normalized_path="typed/cancel.mp3")
        mock_db.library.list_songs_with_state.side_effect = [[candidate], []]
        service = _make_service(db=mock_db)

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=1,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.release_claim",
            ) as mock_release_claim,
            patch(
                "nomarr.services.domain.tagging_svc.write.write_file_tags_workflow",
                side_effect=TaskCancelledError("cancelled"),
            ),
        ):
            result = service.write_tags_to_files(_make_library())

        assert result == WriteTagsResult(processed=0, remaining=1, failed=1, outcome="partial")
        mock_release_claim.assert_called_once_with(mock_db, candidate.identity, "reconcile:lib1")


class TestIsRetryable:
    """The single non-retryable predicate over structured facts/outcomes (DD §A2.1)."""

    _NON_RETRYABLE: ClassVar[list[tuple[FsFact | None, WriteOutcome | None]]] = [
        (None, "modified_externally"),
        (None, "probe_unsupported"),
        (None, "song_record_missing"),
        (None, "library_unresolved"),
        (FsFact(presence="absent", kind="resource_missing", errno=2), None),
        (FsFact(presence="unknown", kind="invalid_path", errno=None), None),
        (FsFact(presence="unknown", kind="wrong_resource_type", errno=20), None),
    ]
    _RETRYABLE: ClassVar[list[tuple[FsFact | None, WriteOutcome | None]]] = [
        (None, None),
        (None, "audio_sanity_failed"),
        (None, "probe_failed_transient"),
        (None, "write_failed"),
        (FsFact(presence="present", kind=None, errno=None), None),
        (FsFact(presence="unknown", kind="unconfirmed_missing", errno=2), None),
        (FsFact(presence="unknown", kind="permission_denied", errno=13), None),
        (FsFact(presence="unknown", kind="storage_unavailable", errno=116), None),
        (FsFact(presence="unknown", kind="transient_io", errno=5), None),
        (FsFact(presence="unknown", kind="storage_full", errno=28), None),
        (FsFact(presence="unknown", kind="read_only_fs", errno=30), None),
        (FsFact(presence="unknown", kind="unknown", errno=None), None),
    ]

    @pytest.mark.unit
    @pytest.mark.parametrize(("fact", "outcome"), _NON_RETRYABLE)
    def test_is_retryable_non_retryable_values(self, fact: FsFact | None, outcome: WriteOutcome | None) -> None:
        """Every non-retryable structured value is classified as not retryable."""
        assert _is_retryable(fact, outcome) is False

    @pytest.mark.unit
    @pytest.mark.parametrize(("fact", "outcome"), _RETRYABLE)
    def test_is_retryable_retryable_values(self, fact: FsFact | None, outcome: WriteOutcome | None) -> None:
        """Every other structured value is retryable (fail-safe default)."""
        assert _is_retryable(fact, outcome) is True


class TestCommitPendingTagsRealCallerClosure:
    """Non-mock closure for the ``commit_pending_tags`` single-pass caller."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_commit_pending_tags_real_caller_accepts_omitted_new_kwargs(self) -> None:
        """The real ``commit_pending_tags`` still calls the real ``write_tags_to_files``.

        The DB is the mocked boundary; the caller and the ``write_tags_to_files``
        implementation are real. The call omits the new keyword-only parameters, so
        this pins that the Protocol/implementation signature extension stays
        backward compatible (no ``TypeError``) and still returns ``CommitResult``.
        """
        mock_db = MagicMock()
        mock_db.app.get_calibration_version.return_value = None
        mock_db.app.count_songs_with_state.return_value = 1
        mock_db.library.list_songs_with_state.return_value = []
        service = _make_service(db=mock_db)

        result: CommitResult = service.commit_pending_tags(_make_library())

        assert result["started"] is True
        assert result["pending_files"] == 1


@pytest.mark.unit
@pytest.mark.mocked
class TestReplacementAccounting:
    """Staged replacements are applied after ordinary writes and remain debt."""

    def test_replacement_is_applied_after_ordinary_write_and_is_partial(self) -> None:
        mock_db = MagicMock()
        mock_db.app.get_calibration_version.return_value = "calibration-v1"
        service = _make_service(db=mock_db)
        library = _make_library()
        ordinary = _candidate("ordinary.mp3")
        replaced = _candidate("replaced.mp3")
        replacement_input = object()
        call_order: list[str] = []

        def workflow(**kwargs: object) -> SimpleNamespace:
            file_key = kwargs["file_key"]
            stage = kwargs["replacement_stage"]
            if file_key == ordinary.identity:
                call_order.append("ordinary")
                return SimpleNamespace(success=True, terminal_outcome="written")
            call_order.append("replaced")
            stage.append((replaced.identity, replacement_input))
            return SimpleNamespace(
                success=True,
                terminal_outcome="replaced",
                replacement_input=(replaced.identity, replacement_input),
            )

        def replacement(file_key: SongIdentity, replacement_value: object) -> None:
            call_order.append("replacement")
            assert file_key is replaced.identity
            assert replacement_value is replacement_input

        mock_db.library.replace_song_for_reimport.side_effect = replacement
        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.claim_files_for_reconciliation",
                return_value=[ordinary, replaced],
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.write_file_tags_workflow",
                side_effect=workflow,
            ),
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=0,
            ),
        ):
            result = service.write_tags_to_files(library)

        assert call_order == ["ordinary", "replaced", "replacement"]
        assert result.processed == 1
        assert result.failed == 0
        assert result.remaining == 1
        assert result.outcome == "partial"
        mock_db.library.replace_song_for_reimport.assert_called_once_with(replaced.identity, replacement_input)
