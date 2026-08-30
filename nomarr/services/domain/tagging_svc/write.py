"""File tag I/O and reconciliation operations for TaggingService."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_song_state_comp import bulk_set_tags_not_fresh
from nomarr.components.library.reconciliation_comp import (
    claim_files_for_reconciliation,
    count_files_needing_reconciliation,
    release_claim,
)
from nomarr.helpers import ManagedTask
from nomarr.helpers.dto.library_dto import WriteTagsResult
from nomarr.helpers.exceptions import TaskCancelledError
from nomarr.services.domain.library_svc.task_ids import write_tags_task_id
from nomarr.workflows.library.file_tags_io_wf import read_file_tags_workflow, remove_file_tags_workflow
from nomarr.workflows.processing.write_file_tags_wf import write_file_tags_workflow

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService


logger = logging.getLogger(__name__)


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

        Returns:
            WriteTagsResult with processed, remaining, and failed counts

        """
        target_mode = library.file_write_mode
        calibration_doc = self.db.app.get_config_option("calibration_version")
        calibration_hash = None if calibration_doc is None else calibration_doc.value
        has_calibration = bool(calibration_hash)

        worker_id = f"reconcile:{library.name}"
        claimed_files = claim_files_for_reconciliation(
            self.db,
            library=library,
            worker_id=worker_id,
            batch_size=batch_size,
        )

        processed = 0
        failed = 0

        for file_doc in claimed_files:
            file_key = str(file_doc["id"])
            try:
                result = write_file_tags_workflow(
                    db=self.db,
                    file_key=file_key,
                    worker_id=worker_id,
                    target_mode=target_mode,
                    has_calibration=has_calibration,
                    namespace=namespace,
                )
                if result.success:
                    processed += 1
                elif result.error == "file_modified_externally":
                    logger.debug(
                        f"[reconcile] Skipping {file_key}: modified externally, will retry after rescan",
                    )
                    release_claim(self.db, file_key, worker_id)
                else:
                    failed += 1
                    release_claim(self.db, file_key, worker_id)
                    logger.warning(f"[reconcile] Failed to write tags for {file_key}: {result.error}")
            except Exception as e:
                failed += 1
                logger.exception(f"[reconcile] Error processing {file_key}: {e}")
                try:
                    release_claim(self.db, file_key, worker_id)
                except Exception as release_err:
                    logger.warning(f"[reconcile] Failed to release claim for {file_key}: {release_err}", exc_info=True)

        remaining = count_files_needing_reconciliation(self.db, library=library)

        logger.info(
            f"[reconcile] Library {library.name}: processed={processed}, failed={failed}, remaining={remaining}"
        )

        return WriteTagsResult(
            processed=processed,
            remaining=remaining,
            failed=failed,
        )

    def start_write_tags_background(
        self,
        library: Library,
        stop_event: threading.Event,
        on_complete: Callable[[], None] | None = None,
    ) -> str:
        """Dispatch a non-blocking background write-tags loop for a library.

        Starts a managed background task that repeatedly calls
        :meth:`write_tags_to_files` for the given library until either all pending
        tag writes have been processed (``remaining == 0``) or ``stop_event`` is
        set.

        If the loop is cancelled while files remain pending, it raises
        ``TaskCancelledError`` so the background task service records the task as
        ``cancelled`` (never ``complete``) and skips ``on_complete`` — leaving the
        library's tag-write work resumable rather than falsely reported written.

        Args:
            library: Domain ``Library`` (natural identity) to write.
            stop_event: Cooperative cancellation event. The background loop exits
                when this event is set.
            on_complete: Optional callback invoked only after the loop drains all
                pending writes (``remaining == 0``). It is skipped on
                cancellation or failure.

        Returns:
            Task ID string in the form ``"write_tags:{library.name}"`` returned by
            the background task service. Use this ID for status polling and
            cancellation.

        """
        task_id = write_tags_task_id(library)

        def _task() -> WriteTagsResult:
            last_result = WriteTagsResult(processed=0, remaining=0, failed=0)
            while not stop_event.is_set():
                result = self.write_tags_to_files(library)
                last_result = result
                if result.remaining == 0:
                    return last_result
                stop_event.wait(1.0)
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
            Dict with pending_count, failed_count, and in_progress status

        """
        pending_count = count_files_needing_reconciliation(self.db, library=library)
        task_status = self._bts.get_task_status(write_tags_task_id(library))
        in_progress = task_status is not None and task_status["status"] == "running"
        task_result = task_status.get("result") if task_status is not None else None
        failed_count = task_result.failed if isinstance(task_result, WriteTagsResult) else 0

        return {
            "pending_count": pending_count,
            "failed_count": failed_count,
            "in_progress": in_progress,
        }
