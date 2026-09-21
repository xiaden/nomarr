"""Spec-first RED regressions for the bounded tag-write reconciliation run.

Plan: ``TASK-canonical-filesystem-access-F-tag-write-terminal-failure-policy``,
Phase 1 (spec-first). These tests drive the REAL ``TaggingService._task`` loop
through a REAL ``BackgroundTaskService`` (no BTS mock) while only the DB/workflow
boundary (``claim_files_for_reconciliation``,
``count_files_needing_reconciliation``, ``release_claim`` and
``write_file_tags_workflow``) is mocked, following the template
``tests/unit/workflows/library/test_scan_cancellation_terminal.py``.

They are authored against the eventually-required behaviour (ADR-051 /
``DD-tag-write-reconciliation-terminal-failure.md`` v0.8):

- a bounded per-file retry budget ``_MAX_WRITE_ATTEMPTS = 3`` per run;
- run-scoped exclusion after a non-retryable failure or budget exhaustion;
- a three-exit loop: drained (``complete``), no-eligible-candidate (``partial``),
  or ``stop_event`` (``TaskCancelledError`` / BTS ``cancelled``);
- a partial run published as BTS ``complete`` carrying
  ``WriteTagsResult(outcome="partial")``;
- a fresh run-local budget on every independent dispatch.

Every assertion is expected to FAIL at HEAD and pass once Phase 3 lands the
bounded-retry driver. A regression that reintroduces unbounded re-claiming must
fail the bounded ``thread.join(timeout=2.0)`` as a timeout assertion, never hang.
"""

from __future__ import annotations

import importlib
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
from nomarr.helpers.fs_contract import FsFact
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig
from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_WRITE_MODULE = "nomarr.services.domain.tagging_svc.write"

# A bounded join that is generous for the future fast loop but still fails as a
# timeout (never hangs) at HEAD, where the oldest loop re-claims forever.
_TERMINAL_JOIN_TIMEOUT_S = 2.0


# ---------------------------------------------------------------------------
# Domain fixtures (mirroring tests/unit/services/domain/test_tagging_svc_write_tags.py)
# ---------------------------------------------------------------------------


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


def _failure(
    *,
    outcome: str | None = None,
    fs_fact: FsFact | None = None,
    error: str = "Safe write failed: persistent",
) -> SimpleNamespace:
    """Duck-typed future ``WriteResult`` failure carrying structured fields.

    ``error`` is retained only so the HEAD workflow's string branch cannot crash;
    the target implementation reads ``outcome``/``fs_fact`` and never branches on
    the string.
    """
    return SimpleNamespace(success=False, outcome=outcome, fs_fact=fs_fact, error=error)


def _success() -> SimpleNamespace:
    """Duck-typed successful ``WriteResult``."""
    return SimpleNamespace(success=True, outcome=None, fs_fact=None, error=None)


def _noop(*args: object, **kwargs: object) -> None:
    """Mocked ``release_claim`` that accepts any call shape and does nothing."""
    del args, kwargs


def _workflow_failing(
    *,
    outcome: str | None = None,
    fs_fact: FsFact | None = None,
) -> Callable[..., SimpleNamespace]:
    """Return a mocked ``write_file_tags_workflow`` that always fails structurally."""
    result = _failure(outcome=outcome, fs_fact=fs_fact)

    def _workflow(**kwargs: object) -> SimpleNamespace:
        del kwargs
        return result

    return _workflow


def _make_service(db: MagicMock, bts: BackgroundTaskService) -> TaggingService:
    """Build a real ``TaggingService`` over a real ``BackgroundTaskService``."""
    return TaggingService(
        database=db,
        cfg=TaggingServiceConfig(
            models_dir="models",
            namespace="nom",
            version_tag_key="nom:version",
        ),
        bts=bts,
        config_service=MagicMock(),
    )


@contextmanager
def _boundary(
    *,
    workflow: Callable[..., SimpleNamespace],
    claim: Callable[..., list[SongStateCandidate]],
    count: Callable[..., int],
    inter_attempt_delay: float = 0.01,
) -> Iterator[None]:
    """Patch only the DB/workflow boundary plus the inter-attempt delay constant.

    ``_INTER_ATTEMPT_DELAY_SECONDS`` does not exist at HEAD; ``create=True``
    installs it so the future driver runs fast without changing the production
    loop (HEAD ignores it and still uses its literal 1 s wait).
    """
    write_module = importlib.import_module(_WRITE_MODULE)
    with (
        patch(f"{_WRITE_MODULE}.write_file_tags_workflow", new=workflow),
        patch(f"{_WRITE_MODULE}.claim_files_for_reconciliation", new=claim),
        patch(f"{_WRITE_MODULE}.count_files_needing_reconciliation", new=count),
        patch(f"{_WRITE_MODULE}.release_claim", new=_noop),
        patch.object(write_module, "_INTER_ATTEMPT_DELAY_SECONDS", inter_attempt_delay, create=True),
    ):
        yield


def _start(
    service: TaggingService,
    bts: BackgroundTaskService,
    library: Library,
    *,
    on_complete: Callable[[], None] | None = None,
) -> tuple[threading.Event, str, threading.Thread]:
    """Dispatch the real managed task and return its stop event, id, and thread."""
    stop_event = threading.Event()
    task_id = service.start_write_tags_background(library, stop_event, on_complete=on_complete)
    thread = bts._tasks[task_id][0]
    return stop_event, task_id, thread


def _finish(stop_event: threading.Event, thread: threading.Thread) -> None:
    """Release any still-running loop so a RED failure cannot leak a live thread."""
    stop_event.set()
    thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)


class TestTerminalDrive:
    """The real ``_task`` driver must terminate under persistent per-file failure."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_run_terminates_terminal_when_one_file_fails_persistently(self) -> None:
        """One persistently failing file must not keep the managed task running forever."""
        db = MagicMock()
        db.app.get_calibration_version.return_value = "calibration-v1"
        bts = BackgroundTaskService()
        service = _make_service(db, bts)
        library = _make_library()
        failing = _identity()

        def _claim(db, library, worker_id, batch_size=100, lease_ms=60000, *, exclude_locators=()):
            if failing in exclude_locators:
                return []
            return [_candidate()]

        def _count(db, library, *, exclude_locators=()):
            return 0 if failing in exclude_locators else 1

        with _boundary(workflow=_workflow_failing(outcome="write_failed"), claim=_claim, count=_count):
            stop_event, task_id, thread = _start(service, bts, library)
            try:
                thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)
                assert not thread.is_alive(), (
                    "write-tags run did not reach a terminal state within the bounded join; "
                    "the loop still re-claims a persistently failing file (RED)"
                )
                status = bts.get_task_status(task_id)
                assert status is not None
                assert status["status"] == "complete"
            finally:
                _finish(stop_event, thread)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_terminal_partial_run_publishes_complete_with_partial_outcome(self) -> None:
        """A run that cannot drain publishes BTS ``complete`` with ``outcome=partial``."""
        db = MagicMock()
        db.app.get_calibration_version.return_value = "calibration-v1"
        bts = BackgroundTaskService()
        service = _make_service(db, bts)
        library = _make_library()
        failing = _identity()

        def _claim(db, library, worker_id, batch_size=100, lease_ms=60000, *, exclude_locators=()):
            if failing in exclude_locators:
                return []
            return [_candidate()]

        def _count(db, library, *, exclude_locators=()):
            return 0 if failing in exclude_locators else 1

        with _boundary(workflow=_workflow_failing(outcome="write_failed"), claim=_claim, count=_count):
            stop_event, task_id, thread = _start(service, bts, library)
            try:
                thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)
                assert not thread.is_alive()
                status = bts.get_task_status(task_id)
                assert status is not None and status["status"] == "complete"
                result = status["result"]
                assert result is not None
                assert result.outcome == "partial"
                assert result.remaining > 0
                assert result.processed == 0
            finally:
                _finish(stop_event, thread)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_on_complete_invoked_exactly_once(self) -> None:
        """A partial run reaches ``complete`` so ``on_complete`` fires exactly once."""
        db = MagicMock()
        db.app.get_calibration_version.return_value = "calibration-v1"
        bts = BackgroundTaskService()
        service = _make_service(db, bts)
        library = _make_library()
        failing = _identity()
        on_complete_calls: list[str] = []

        def _claim(db, library, worker_id, batch_size=100, lease_ms=60000, *, exclude_locators=()):
            if failing in exclude_locators:
                return []
            return [_candidate()]

        def _count(db, library, *, exclude_locators=()):
            return 0 if failing in exclude_locators else 1

        with _boundary(workflow=_workflow_failing(outcome="write_failed"), claim=_claim, count=_count):
            stop_event, task_id, thread = _start(
                service, bts, library, on_complete=lambda _result: on_complete_calls.append("called")
            )
            try:
                thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)
                assert not thread.is_alive()
                assert on_complete_calls == ["called"]
                status = bts.get_task_status(task_id)
                assert status is not None and status["status"] == "complete"
            finally:
                _finish(stop_event, thread)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_completed_run_does_not_reclaim_excluded_locator(self) -> None:
        """Once a locator is excluded the completed run never re-claims it."""
        db = MagicMock()
        db.app.get_calibration_version.return_value = "calibration-v1"
        bts = BackgroundTaskService()
        service = _make_service(db, bts)
        library = _make_library()
        failing = _identity()
        claim_returns: list[SongIdentity] = []

        def _claim(db, library, worker_id, batch_size=100, lease_ms=60000, *, exclude_locators=()):
            if failing in exclude_locators:
                return []
            claim_returns.append(failing)
            return [_candidate()]

        def _count(db, library, *, exclude_locators=()):
            return 0 if failing in exclude_locators else 1

        with _boundary(workflow=_workflow_failing(outcome="write_failed"), claim=_claim, count=_count):
            stop_event, task_id, thread = _start(service, bts, library)
            try:
                thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)
                assert not thread.is_alive()
                assert len(claim_returns) == 3
                status = bts.get_task_status(task_id)
                assert status is not None and status["status"] == "complete"
            finally:
                _finish(stop_event, thread)


class TestRetryBudget:
    """Run-local bounded retry accounting and fresh-budget semantics."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_retryable_failure_attempted_at_most_max_write_attempts_then_excluded(self) -> None:
        """A retryable failure is attempted exactly ``_MAX_WRITE_ATTEMPTS`` times, then excluded."""
        write_module = importlib.import_module(_WRITE_MODULE)
        max_attempts = getattr(write_module, "_MAX_WRITE_ATTEMPTS", None)
        assert max_attempts == 3

        db = MagicMock()
        db.app.get_calibration_version.return_value = "calibration-v1"
        bts = BackgroundTaskService()
        service = _make_service(db, bts)
        library = _make_library()
        failing = _identity()
        claim_returns: list[SongIdentity] = []

        def _claim(db, library, worker_id, batch_size=100, lease_ms=60000, *, exclude_locators=()):
            if failing in exclude_locators:
                return []
            claim_returns.append(failing)
            return [_candidate()]

        def _count(db, library, *, exclude_locators=()):
            return 0 if failing in exclude_locators else 1

        with _boundary(workflow=_workflow_failing(outcome="write_failed"), claim=_claim, count=_count):
            stop_event, task_id, thread = _start(service, bts, library)
            try:
                thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)
                assert not thread.is_alive()
                assert len(claim_returns) == max_attempts
                status = bts.get_task_status(task_id)
                assert status is not None and status["status"] == "complete"
                assert status["result"].outcome == "partial"
            finally:
                _finish(stop_event, thread)

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(
        ("outcome", "fs_fact"),
        [
            pytest.param("modified_externally", None, id="modified_externally"),
            pytest.param("probe_unsupported", None, id="probe_unsupported"),
            pytest.param("song_record_missing", None, id="song_record_missing"),
            pytest.param("library_unresolved", None, id="library_unresolved"),
            pytest.param(None, FsFact(presence="absent", kind="resource_missing", errno=2), id="corroborated_absent"),
            pytest.param(None, FsFact(presence="unknown", kind="invalid_path", errno=None), id="invalid_path"),
            pytest.param(
                None, FsFact(presence="unknown", kind="wrong_resource_type", errno=20), id="wrong_resource_type"
            ),
        ],
    )
    def test_non_retryable_outcome_excluded_on_first_failure(self, outcome: str | None, fs_fact: FsFact | None) -> None:
        """Each non-retryable structured value is excluded after a single attempt (zero retries)."""
        db = MagicMock()
        db.app.get_calibration_version.return_value = "calibration-v1"
        bts = BackgroundTaskService()
        service = _make_service(db, bts)
        library = _make_library()
        failing = _identity()
        claim_returns: list[SongIdentity] = []

        def _claim(db, library, worker_id, batch_size=100, lease_ms=60000, *, exclude_locators=()):
            if failing in exclude_locators:
                return []
            claim_returns.append(failing)
            return [_candidate()]

        def _count(db, library, *, exclude_locators=()):
            return 0 if failing in exclude_locators else 1

        with _boundary(
            workflow=_workflow_failing(outcome=outcome, fs_fact=fs_fact),
            claim=_claim,
            count=_count,
        ):
            stop_event, task_id, thread = _start(service, bts, library)
            try:
                thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)
                assert not thread.is_alive()
                assert len(claim_returns) == 1
                status = bts.get_task_status(task_id)
                assert status is not None and status["status"] == "complete"
                assert status["result"].outcome == "partial"
            finally:
                _finish(stop_event, thread)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_new_dispatch_receives_fresh_retry_budget(self) -> None:
        """A second independent dispatch re-attempts up to the budget with a fresh run-local budget."""
        db = MagicMock()
        db.app.get_calibration_version.return_value = "calibration-v1"
        bts = BackgroundTaskService()
        service = _make_service(db, bts)
        library = _make_library()
        failing = _identity()
        claim_returns: list[SongIdentity] = []

        def _claim(db, library, worker_id, batch_size=100, lease_ms=60000, *, exclude_locators=()):
            if failing in exclude_locators:
                return []
            claim_returns.append(failing)
            return [_candidate()]

        def _count(db, library, *, exclude_locators=()):
            return 0 if failing in exclude_locators else 1

        with _boundary(workflow=_workflow_failing(outcome="write_failed"), claim=_claim, count=_count):
            first_stop, first_id, first_thread = _start(service, bts, library)
            try:
                first_thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)
                assert not first_thread.is_alive()
                assert len(claim_returns) == 3
                first_status = bts.get_task_status(first_id)
                assert first_status is not None and first_status["status"] == "complete"
            finally:
                _finish(first_stop, first_thread)

            # First run's exclusion is run-local: the fresh dispatch starts empty.
            assert claim_returns == [failing, failing, failing]

            second_stop, second_id, second_thread = _start(service, bts, library)
            try:
                second_thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)
                assert not second_thread.is_alive()
                assert len(claim_returns) == 6
                second_status = bts.get_task_status(second_id)
                assert second_status is not None and second_status["status"] == "complete"
            finally:
                _finish(second_stop, second_thread)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_cancel_during_inter_attempt_delay_exits_promptly(self) -> None:
        """A ``stop_event`` set during the inter-attempt delay exits as ``cancelled`` without hanging."""
        db = MagicMock()
        db.app.get_calibration_version.return_value = "calibration-v1"
        bts = BackgroundTaskService()
        service = _make_service(db, bts)
        library = _make_library()
        failing = _identity()

        def _claim(db, library, worker_id, batch_size=100, lease_ms=60000, *, exclude_locators=()):
            if failing in exclude_locators:
                return []
            return [_candidate()]

        def _count(db, library, *, exclude_locators=()):
            return 0 if failing in exclude_locators else 1

        with _boundary(
            workflow=_workflow_failing(outcome="write_failed"),
            claim=_claim,
            count=_count,
            inter_attempt_delay=1.0,
        ):
            stop_event, task_id, thread = _start(service, bts, library)
            setter = threading.Timer(0.2, stop_event.set)
            setter.start()
            try:
                thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)
                assert not thread.is_alive(), "cancellation during the inter-attempt delay hung the loop"
                status = bts.get_task_status(task_id)
                assert status is not None and status["status"] == "cancelled"
                assert status["result"].outcome == "partial"
            finally:
                setter.cancel()
                _finish(stop_event, thread)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_escaped_workflow_exception_is_retried_bounded_then_partial(self) -> None:
        """A raising workflow is retried up to the budget, then the run ends partial (no infinite loop)."""
        write_module = importlib.import_module(_WRITE_MODULE)
        max_attempts = getattr(write_module, "_MAX_WRITE_ATTEMPTS", None)
        assert max_attempts == 3

        db = MagicMock()
        db.app.get_calibration_version.return_value = "calibration-v1"
        bts = BackgroundTaskService()
        service = _make_service(db, bts)
        library = _make_library()
        failing = _identity()
        claim_returns: list[SongIdentity] = []

        def _raising_workflow(**kwargs: object) -> SimpleNamespace:
            del kwargs
            raise RuntimeError("escaped write failure")

        def _claim(db, library, worker_id, batch_size=100, lease_ms=60000, *, exclude_locators=()):
            if failing in exclude_locators:
                return []
            claim_returns.append(failing)
            return [_candidate()]

        def _count(db, library, *, exclude_locators=()):
            return 0 if failing in exclude_locators else 1

        with _boundary(workflow=_raising_workflow, claim=_claim, count=_count):
            stop_event, task_id, thread = _start(service, bts, library)
            try:
                thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)
                assert not thread.is_alive(), "escaped-exception retries did not terminate the run"
                assert len(claim_returns) == max_attempts
                status = bts.get_task_status(task_id)
                assert status is not None and status["status"] == "complete"
                assert status["result"] is not None
                assert status["result"].outcome == "partial"
                assert status["result"].remaining > 0
            finally:
                _finish(stop_event, thread)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_lease_held_candidate_does_not_manufacture_false_partial(self) -> None:
        """A pass claiming nothing while eligible work remains keeps waiting instead of ending partial."""
        db = MagicMock()
        db.app.get_calibration_version.return_value = "calibration-v1"
        bts = BackgroundTaskService()
        service = _make_service(db, bts)
        library = _make_library()

        def _claim(db, library, worker_id, batch_size=100, lease_ms=60000, *, exclude_locators=()):
            del exclude_locators
            return []

        def _count(db, library, *, exclude_locators=()):
            del exclude_locators
            return 1

        with _boundary(
            workflow=_workflow_failing(outcome="write_failed"),
            claim=_claim,
            count=_count,
            inter_attempt_delay=0.05,
        ):
            stop_event, task_id, thread = _start(service, bts, library)
            setter = threading.Timer(0.2, stop_event.set)
            setter.start()
            try:
                thread.join(timeout=_TERMINAL_JOIN_TIMEOUT_S)
                assert not thread.is_alive(), "lease-held wait did not exit on cancellation"
                status = bts.get_task_status(task_id)
                assert status is not None
                assert status["status"] == "cancelled"
                assert status["result"].outcome == "partial"
            finally:
                setter.cancel()
                _finish(stop_event, thread)
