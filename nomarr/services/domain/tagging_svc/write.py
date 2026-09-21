"""File tag I/O and reconciliation operations for TaggingService."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final, Literal

from nomarr.components.library.library_song_state_comp import bulk_set_tags_not_fresh
from nomarr.components.library.reconciliation_comp import (
    claim_files_for_reconciliation,
    count_files_needing_reconciliation,
    release_claim,
)
from nomarr.helpers import ManagedTask
from nomarr.helpers.dto.library_dto import WriteTagsResult
from nomarr.helpers.exceptions import LibraryOperationConflict, TaskCancelledError
from nomarr.services.domain.library_svc.task_ids import write_tags_task_id
from nomarr.workflows.library.file_tags_io_wf import read_file_tags_workflow, remove_file_tags_workflow
from nomarr.workflows.processing.write_file_tags_wf import write_file_tags_workflow

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dto.library_dto import WriteOutcome
    from nomarr.helpers.fs_contract import FsFact
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService


logger = logging.getLogger(__name__)

# Bounded run-local per-file retry policy (ADR-051 item 1; DD §1). A locator is
# attempted at most ``_MAX_WRITE_ATTEMPTS`` times per run; budget exhaustion enters
# the run-scoped exclusion set. The inter-attempt delay is fixed, bounded, in-run
# only, and cancellation-responsive via ``stop_event.wait``. There is no persistent
# cooldown, scheduler, background-task-level retry machinery, or durable ledger.
_MAX_WRITE_ATTEMPTS: Final[int] = 3
_INTER_ATTEMPT_DELAY_SECONDS: Final[float] = 1.0


def _is_retryable(fact: FsFact | None, outcome: WriteOutcome | None) -> bool:
    """Decide whether a failed tag write may be re-attempted within the same run.

    The single non-retryable predicate over the canonical structured outcome
    (ADR-051 item 1; DD §A2.1). Non-retryable iff the outcome is
    ``modified_externally`` (semantic conflict), ``probe_unsupported``
    (deterministic), or a known domain miss (``song_record_missing`` /
    ``library_unresolved``), or the fact corroborates absence, or the fact kind is
    ``invalid_path`` / ``wrong_resource_type``. Everything else
    (transient/storage/permission/unconfirmed kinds, ``audio_sanity_failed``,
    ``probe_failed_transient``, ``write_failed``, and ``None``/unknown) is
    retryable-bounded — the fail-safe default. This function never inspects an
    error string.
    """
    non_retryable = (
        outcome == "modified_externally"
        or outcome == "probe_unsupported"
        or outcome == "song_record_missing"
        or outcome == "library_unresolved"
        or (fact is not None and fact.presence == "absent")
        or (fact is not None and fact.kind in {"invalid_path", "wrong_resource_type"})
    )
    return not non_retryable


class TaggingWriteMixin:
    """Mixin providing file tag I/O and reconciliation methods."""

    db: Database
    _bts: BackgroundTaskService

    def read_file_tags(self, path: str, namespace: str) -> dict[str, Any]:
        """Read tags from an audio file.

        Args:
            path: Absolute file path
            namespace: Tag namespace to filter by

        Returns:
            Dictionary of tag_key -> value(s)

        Raises:
            ValueError: If path is invalid
            RuntimeError: If file cannot be read

        """
        return read_file_tags_workflow(db=self.db, path=path, namespace=namespace)

    def remove_file_tags(self, path: str, namespace: str) -> int:
        """Remove all namespaced tags from an audio file.

        Args:
            path: Absolute file path
            namespace: Tag namespace to remove

        Returns:
            Number of tags removed

        Raises:
            ValueError: If path is invalid
            RuntimeError: If file cannot be modified

        """
        return remove_file_tags_workflow(db=self.db, path=path, namespace=namespace)

    def write_tags_to_files(
        self,
        library: Library,
        batch_size: int = 100,
        namespace: str = "nom",
        *,
        exclude_locators: set[SongIdentity] | None = None,
        retry_counts: dict[SongIdentity, int] | None = None,
    ) -> WriteTagsResult:
        """Write pending file tags for a library based on its file_write_mode.

        Claims files with mismatched projection state and writes tags according
        to the library's current mode and calibration. This handles:
        - Mode changes (e.g., switching from "full" to "minimal")
        - Calibration updates (new mood tag values)
        - New ML results (files analyzed but never written)

        Args:
            library: Domain ``Library`` (natural identity) to write.
            batch_size: Number of files to process per batch
            namespace: Tag namespace (default: "nom")
            exclude_locators: Run-owned exclusion set used as the claim filter. When
                provided, non-retryable failures and retry-budget exhaustion add the
                locator to it in place. ``None`` (the single-pass caller) creates no
                run-local state.
            retry_counts: Run-owned per-locator attempt counter, mutated in place for
                retryable failures. ``None`` disables retry accounting.

        Returns:
            WriteTagsResult with processed, remaining (the plain, non-exclusion-aware
            pending count), failed, and outcome (``"complete"`` only when nothing is
            pending).

        """
        self.db.library.regions.admit_tag_write(library)
        return self._write_admitted_tags_to_files(
            library,
            batch_size=batch_size,
            namespace=namespace,
            exclude_locators=exclude_locators,
            retry_counts=retry_counts,
        )

    def _write_admitted_tags_to_files(
        self,
        library: Library,
        batch_size: int = 100,
        namespace: str = "nom",
        *,
        exclude_locators: set[SongIdentity] | None = None,
        retry_counts: dict[SongIdentity, int] | None = None,
        requested_mode: Literal["none", "files", "database"] = "none",
    ) -> WriteTagsResult:
        """Execute one admitted write batch without reacquiring lifecycle state."""
        target_mode = library.file_write_mode
        calibration_hash = self.db.app.get_calibration_version()
        has_calibration = bool(calibration_hash)

        worker_id = f"reconcile:{library.name}"
        claimed_files = claim_files_for_reconciliation(
            self.db,
            library=library,
            worker_id=worker_id,
            batch_size=batch_size,
            exclude_locators=exclude_locators or (),
        )

        processed = 0
        failed = 0

        def _record_failure(file_key: SongIdentity, result: Any | None) -> None:
            """Apply the run-local retry/exclusion accounting for one non-success."""
            fact = result.fs_fact if result is not None else None
            outcome = result.outcome if result is not None else None
            if not _is_retryable(fact, outcome):
                if exclude_locators is not None:
                    exclude_locators.add(file_key)
                return
            if retry_counts is not None:
                attempts = retry_counts.get(file_key, 0) + 1
                retry_counts[file_key] = attempts
                if attempts >= _MAX_WRITE_ATTEMPTS and exclude_locators is not None:
                    exclude_locators.add(file_key)

        # ``claim_files_for_reconciliation`` returns typed ``SongStateCandidate`` values;
        # each candidate already carries the locator to re-address, so no path/identity is
        # reconstructed at this boundary (ADR-048; locator-addressing contract). A missing library UUID
        # yields no candidates from the claim read, so the loop is a no-op for that case.
        for candidate in claimed_files:
            file_key = candidate.identity
            try:
                result = write_file_tags_workflow(
                    db=self.db,
                    file_key=file_key,
                    worker_id=worker_id,
                    target_mode=target_mode,
                    has_calibration=has_calibration,
                    namespace=namespace,
                    requested_mode=requested_mode,
                )
                if result.success:
                    processed += 1
                elif result.outcome == "modified_externally":
                    logger.debug("[reconcile] Skipping modified file; will retry after rescan")
                    release_claim(self.db, file_key, worker_id)
                    # Benign skip: release and exclude, but do not count as failed.
                    _record_failure(file_key, result)
                else:
                    failed += 1
                    release_claim(self.db, file_key, worker_id)
                    logger.warning("[reconcile] Failed to write tags for locator: %s", file_key)
                    _record_failure(file_key, result)
            except LibraryOperationConflict:
                raise
            except Exception as e:
                failed += 1
                logger.exception("[reconcile] Error processing locator: %s", e)
                try:
                    release_claim(self.db, file_key, worker_id)
                except Exception as release_err:
                    logger.warning("[reconcile] Failed to release claim: %s", release_err, exc_info=True)
                # The attempt counter is incremented independently of the best-effort
                # release, so a failed release cannot break termination.
                _record_failure(file_key, None)

        remaining = count_files_needing_reconciliation(self.db, library=library)

        logger.info(
            f"[reconcile] Library {library.name}: processed={processed}, failed={failed}, remaining={remaining}"
        )

        return WriteTagsResult(
            processed=processed,
            remaining=remaining,
            failed=failed,
            outcome="complete" if remaining == 0 else "partial",
        )

    def start_write_tags_background(
        self,
        library: Library,
        stop_event: threading.Event,
        on_complete: Callable[[], None] | None = None,
        *,
        admitted: bool = False,
        requested_mode: Literal["none", "files", "database"] = "none",
    ) -> str:
        """Dispatch a non-blocking background write-tags loop for a library.

        Starts a managed background task that drives the bounded three-exit loop:

        1. ``remaining == 0`` → return the drained result (``outcome="complete"``);
        2. no eligible candidate remains while work is still pending
           (``eligible_remaining == 0 and remaining > 0``) → return a partial
           result (``outcome="partial"``) so the task still reaches BTS
           ``complete`` and ``on_complete`` fires with a partial signal;
        3. ``stop_event`` set with work outstanding → raise ``TaskCancelledError``
           so the background task service records ``cancelled`` and skips
           ``on_complete``.

        Run-local ``exclude`` and ``retry_counts`` are created fresh per dispatch
        and never persisted, so an independently triggered run gets a fresh attempt
        budget. A retryable failure is re-attempted at most ``_MAX_WRITE_ATTEMPTS``
        times before entering the run exclusion set; a non-retryable failure is
        excluded immediately.

        Args:
            library: Domain ``Library`` (natural identity) to write.
            stop_event: Cooperative cancellation event. The background loop exits
                when this event is set.
            on_complete: Optional callback invoked only after the loop terminates
                without outstanding eligible work (full drain or partial terminal).
                It is skipped on cancellation.

        Returns:
            Task ID string in the form ``"write_tags:{library.name}"`` returned by
            the background task service. Use this ID for status polling and
            cancellation.

        """
        # Admission completes before BTS dispatch; the background loop reuses
        # that durable lifecycle state for each bounded batch. Pipeline callers
        # may pass ``admitted`` when they own the same pre-dispatch admission.
        if not admitted:
            self.db.library.regions.admit_tag_write(library)
        task_id = write_tags_task_id(library)

        def _task() -> WriteTagsResult:
            exclude: set[SongIdentity] = set()
            retry_counts: dict[SongIdentity, int] = {}
            last_result = WriteTagsResult(processed=0, remaining=0, failed=0)
            while not stop_event.is_set():
                result = self._write_admitted_tags_to_files(
                    library,
                    exclude_locators=exclude,
                    retry_counts=retry_counts,
                    requested_mode=requested_mode,
                )
                last_result = result
                if result.remaining == 0:
                    return last_result
                # Single owner of the exclusion-aware eligibility count. Leases are
                # not excluded, so a concurrently held candidate keeps the loop
                # waiting rather than manufacturing a false partial.
                eligible_remaining = count_files_needing_reconciliation(self.db, library, exclude_locators=exclude)
                if eligible_remaining == 0:
                    return last_result
                stop_event.wait(_INTER_ATTEMPT_DELAY_SECONDS)
            # The loop exited before reconciliation drained. This is cooperative
            # cancellation with pending work: raise so BTS records "cancelled"
            # instead of "complete" and does not run on_complete (which would
            # otherwise mark the write axis written).
            raise TaskCancelledError("Write cancelled with pending work remaining", result=last_result)

        return self._bts.start_task(
            ManagedTask(
                task_id=task_id,
                fn=_task,
                stop_event=stop_event,
                on_complete=on_complete,
                daemon=True,
            ),
        )

    def mark_tags_not_fresh(self, library: Library) -> int:
        """Mark all file tags in a library as not fresh.

        Args:
            library: Domain ``Library`` (natural identity).

        Returns:
            Number of files marked not fresh

        """
        return bulk_set_tags_not_fresh(self.db, library)

    def get_reconcile_status(self, library: Library) -> dict[str, Any]:
        """Get reconciliation status for a library.

        Args:
            library: Domain ``Library`` (natural identity).

        Returns:
            Dict with pending_count, failed_count, in_progress, and outcome
            (``"running"`` / ``"complete"`` / ``"partial"``). The no-usable-result
            default is conservative: ``pending_count > 0`` → ``"partial"``,
            ``0`` → ``"complete"``.

        """
        pending_count = count_files_needing_reconciliation(self.db, library=library)
        task_status = self._bts.get_task_status(write_tags_task_id(library))
        in_progress = task_status is not None and task_status["status"] == "running"
        task_result = task_status.get("result") if task_status is not None else None
        failed_count = task_result.failed if isinstance(task_result, WriteTagsResult) else 0

        if in_progress:
            outcome = "active"
            message_code = "TAG_WRITE_ACTIVE"
        elif isinstance(task_result, WriteTagsResult):
            # BTS completion is not success authority: only an explicit zero
            # remaining count is a full drain (ADR-051).
            outcome = "written" if task_result.outcome == "complete" and task_result.remaining == 0 else "partial"
            message_code = "TAG_WRITE_COMPLETE" if outcome == "written" else "TAG_WRITE_PARTIAL"
        elif pending_count > 0:
            outcome = "not_written"
            message_code = "TAG_WRITE_PENDING"
        else:
            outcome = "unavailable"
            message_code = "TAG_WRITE_STATUS_UNAVAILABLE"

        return {
            "pending_count": pending_count,
            "failed_count": failed_count,
            "in_progress": in_progress,
            "outcome": outcome,
            "requested_mode": None,
            "selected_run_counts": (
                {"processed": task_result.processed, "failed": task_result.failed, "remaining": task_result.remaining}
                if isinstance(task_result, WriteTagsResult)
                else None
            ),
            "resumable": outcome not in {"written", "unavailable"},
            "recovery_action": "none" if outcome == "written" else "retry",
            "message_code": message_code,
        }
