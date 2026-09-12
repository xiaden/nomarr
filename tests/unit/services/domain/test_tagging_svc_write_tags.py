"""Tests for BTS-backed write-tags behavior in ``nomarr.services.domain.tagging_svc``."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers import ManagedTask
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
from nomarr.helpers.dto.library_dto import WriteTagsResult
from nomarr.helpers.exceptions import TaskCancelledError
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig


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
    """Build a real typed reconciliation candidate (what Q3-E now returns)."""
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
            "write_tags_to_files",
            return_value=SimpleNamespace(remaining=0),
        ) as mock_write_tags:
            task_id = service.start_write_tags_background(library, threading.Event())

            assert task_id == "write_tags:lib1"
            mock_bts.start_task.assert_called_once()
            managed_task = mock_bts.start_task.call_args.args[0]
            assert isinstance(managed_task, ManagedTask)
            assert managed_task.task_id == "write_tags:lib1"

            managed_task.fn()

            mock_write_tags.assert_called_once_with(library)

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
        with patch.object(service, "write_tags_to_files", side_effect=write_results) as mock_write_tags:
            service.start_write_tags_background(_make_library(), threading.Event())

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

        assert result == {"pending_count": 4, "failed_count": 0, "in_progress": True}
        mock_bts.get_task_status.assert_called_once_with("write_tags:lib1")

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

        assert result == {"pending_count": 2, "failed_count": 0, "in_progress": False}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_reconcile_status_exposes_completed_failures(self) -> None:
        """Completed write batches expose failures alongside pending work."""
        mock_db = MagicMock()
        mock_bts = MagicMock()
        mock_bts.get_task_status.return_value = {
            "status": "complete",
            "result": WriteTagsResult(processed=1, remaining=2, failed=2),
        }
        service = _make_service(db=mock_db, bts=mock_bts)

        with (
            patch(
                "nomarr.services.domain.tagging_svc.write.count_files_needing_reconciliation",
                return_value=2,
            ),
        ):
            result = service.get_reconcile_status(_make_library())

        assert result == {"pending_count": 2, "failed_count": 2, "in_progress": False}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_background_task_returns_last_write_result(self) -> None:
        """BTS stores the batch result so status polling can expose failures."""
        mock_db = MagicMock()
        mock_bts = MagicMock()
        service = _make_service(db=mock_db, bts=mock_bts)
        batch_result = WriteTagsResult(processed=1, remaining=0, failed=1)
        mock_bts.start_task.side_effect = lambda task: task.fn()

        with patch.object(service, "write_tags_to_files", return_value=batch_result):
            result = service.start_write_tags_background(_make_library(), threading.Event())

        assert result == batch_result


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

        assert result == WriteTagsResult(processed=2, remaining=0, failed=0)
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
                    SimpleNamespace(success=False, error="write_error"),
                ],
            ),
        ):
            result = service.write_tags_to_files(library)

        assert result == WriteTagsResult(processed=1, remaining=0, failed=1)
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
                return_value=SimpleNamespace(success=False, error="file_modified_externally"),
            ),
        ):
            result = service.write_tags_to_files(library)

        assert result == WriteTagsResult(processed=0, remaining=0, failed=0)
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

        assert result == WriteTagsResult(processed=0, remaining=0, failed=1)
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

        assert result == WriteTagsResult(processed=0, remaining=0, failed=0)
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

        assert result == WriteTagsResult(processed=0, remaining=0, failed=1)
        mock_release_claim.assert_called_once_with(mock_db, _identity(), "reconcile:lib1")


class TestWriteTagsToFilesTypedClaims:
    """Regression coverage for the typed Q3-E reconciliation claim contract."""

    @pytest.mark.unit
    def test_write_tags_to_files_reconciles_real_typed_claims(self) -> None:
        """Real typed claims must be re-addressed through ``candidate.identity``.

        Guards the cross-plan break where the caller read ``song.normalized_path``
        from what Q3-E now returns as a typed ``SongStateCandidate`` (``AttributeError``).
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

        assert result == WriteTagsResult(processed=1, remaining=0, failed=0)
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

        assert result == WriteTagsResult(processed=0, remaining=1, failed=1)
        mock_release_claim.assert_called_once_with(mock_db, candidate.identity, "reconcile:lib1")
