"""File tag I/O and reconciliation operations for TaggingService."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_records_comp import get_library_record
from nomarr.components.library.library_song_state_comp import bulk_set_tags_not_fresh
from nomarr.components.library.reconciliation_comp import (
    claim_files_for_reconciliation,
    count_files_needing_reconciliation,
    release_claim,
)
from nomarr.helpers import ManagedTask
from nomarr.helpers.dto.library_dto import WriteTagsResult
from nomarr.workflows.library.file_tags_io_wf import read_file_tags_workflow, remove_file_tags_workflow
from nomarr.workflows.processing.write_file_tags_wf import write_file_tags_workflow

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

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
        library_id: int,
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
            library_id: Library database ID
            batch_size: Number of files to process per batch
            namespace: Tag namespace (default: "nom")

        Returns:
            WriteTagsResult with processed, remaining, and failed counts

        """
        library = get_library_record(self.db, int(library_id))
        if not library:
            msg = f"Library not found: {library_id}"
            raise ValueError(msg)

        target_mode = library.get("file_write_mode", "full")
        calibration_doc = cast("dict[str, Any] | None", self.db.app.get_config_option("calibration_version"))
        calibration_hash = None if calibration_doc is None else calibration_doc["value"]
        has_calibration = bool(calibration_hash)

        worker_id = f"reconcile:{library_id}"
        claimed_files = claim_files_for_reconciliation(
            self.db,
            library_id=library_id,
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
                    release_claim(self.db, file_key)
                else:
                    failed += 1
                    logger.warning(f"[reconcile] Failed to write tags for {file_key}: {result.error}")
            except Exception as e:
                failed += 1
                logger.exception(f"[reconcile] Error processing {file_key}: {e}")
                try:
                    release_claim(self.db, file_key)
                except Exception as release_err:
                    logger.warning(f"[reconcile] Failed to release claim for {file_key}: {release_err}", exc_info=True)

        remaining = count_files_needing_reconciliation(self.db, library_id=library_id)

        logger.info(f"[reconcile] Library {library_id}: processed={processed}, failed={failed}, remaining={remaining}")

        return WriteTagsResult(
            processed=processed,
            remaining=remaining,
            failed=failed,
        )

    def start_write_tags_background(
        self,
        library_id: int,
        stop_event: threading.Event,
        on_complete: Callable[[], None] | None = None,
    ) -> str:
        """Dispatch a non-blocking background write-tags loop for a library.

        Starts a managed background task that repeatedly calls
        :meth:`write_tags_to_files` for the given library until either all pending
        tag writes have been processed (``remaining == 0``) or ``stop_event`` is
        set.

        Args:
            library_id: Library database ID to write
            stop_event: Cooperative cancellation event. The background loop exits
                when this event is set.
            on_complete: Optional callback invoked after successful completion
                when reconciliation finishes with no remaining files.

        Returns:
            Task ID string in the form ``"write_tags:{library_id}"`` returned by
            the background task service. Use this ID for status polling and
            cancellation.

        """
        task_id = f"write_tags:{library_id}"

        def _task() -> None:
            while not stop_event.is_set():
                result = self.write_tags_to_files(library_id)
                if result.remaining == 0:
                    break

        return self._bts.start_task(
            ManagedTask(
                task_id=task_id,
                fn=_task,
                stop_event=stop_event,
                on_complete=on_complete,
                daemon=True,
            ),
        )

    def mark_tags_not_fresh(self, library_id: int) -> int:
        """Mark all file tags in a library as not fresh.

        Args:
            library_id: Library database ID

        Returns:
            Number of files marked not fresh

        """
        return bulk_set_tags_not_fresh(self.db, int(library_id))

    def get_reconcile_status(self, library_id: int) -> dict[str, Any]:
        """Get reconciliation status for a library.

        Args:
            library_id: Library database ID

        Returns:
            Dict with pending_count and in_progress status

        """
        library = get_library_record(self.db, int(library_id))
        if not library:
            msg = f"Library not found: {library_id}"
            raise ValueError(msg)

        pending_count = count_files_needing_reconciliation(self.db, library_id=library_id)
        task_status = self._bts.get_task_status(f"write_tags:{library_id}")
        in_progress = task_status is not None and task_status["status"] == "running"

        return {
            "pending_count": pending_count,
            "in_progress": in_progress,
        }
