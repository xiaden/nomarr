"""Tagging service - applies calibrated tags to library files."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from nomarr.components.library.file_tags_comp import get_file_tags_with_path
from nomarr.components.library.search_files_comp import get_unique_tag_keys, get_unique_tag_values
from nomarr.helpers import ManagedTask
from nomarr.helpers.dto.calibration_dto import (
    GlobalCalibrationStatus,
    LibraryCalibrationStatus,
    WriteCalibratedTagsParams,
)
from nomarr.helpers.dto.library_dto import (
    FileTag,
    FileTagsResult,
    SearchFilesResult,
    TagCleanupResult,
    UniqueTagKeysResult,
    WriteTagsResult,
)
from nomarr.helpers.dto.recalibration_dto import ApplyCalibrationResult
from nomarr.helpers.dto.tag_curation_dto import (
    CommitResult,
    MergeResult,
    RenameResult,
    SplitResult,
    TagListResult,
    TagSongItem,
    TagValueItem,
)
from nomarr.services.domain._library_mapping import map_file_with_tags_to_dto
from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService
from nomarr.workflows.calibration.apply_calibration_wf import apply_calibration_wf
from nomarr.workflows.calibration.write_calibrated_tags_wf import write_calibrated_tags_wf
from nomarr.workflows.library.cleanup_orphaned_tags_wf import cleanup_orphaned_tags_workflow
from nomarr.workflows.library.file_tags_io_wf import read_file_tags_workflow, remove_file_tags_workflow
from nomarr.workflows.processing.write_file_tags_wf import write_file_tags_workflow

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.domain.library_svc import LibraryService
    from nomarr.services.infrastructure.config_svc import ConfigService


logger = logging.getLogger(__name__)

CALIBRATION_APPLY_TASK_ID = "calibration_apply"


class ApplyCalibrationResultDict(TypedDict):
    """Structured apply-calibration result payload."""

    processed: int
    failed: int
    total: int
    message: str


class ApplyCalibrationStatusDict(TypedDict):
    """Background apply lifecycle snapshot."""

    status: Literal["idle", "running", "completed", "failed"]
    result: ApplyCalibrationResultDict | None
    error: str | None


class ApplyCalibrationProgressDict(TypedDict):
    """Background apply per-file progress snapshot."""

    total_files: int
    completed_files: int
    current_file: str | None
    is_running: bool


class ApplyCalibrationCombinedStatusDict(TypedDict):
    """Combined background apply lifecycle and progress snapshot."""

    status: Literal["idle", "running", "completed", "failed"]
    result: ApplyCalibrationResultDict | None
    error: str | None
    total_files: int
    completed_files: int
    current_file: str | None
    is_running: bool


@dataclass
class TaggingServiceConfig:
    """Configuration for TaggingService.

    Attributes:
        models_dir: Path to ML models directory
        namespace: Tag namespace (e.g., "nom")
        version_tag_key: Metadata key for version tracking

    """

    models_dir: str
    namespace: str
    version_tag_key: str


class TaggingService:
    """Service for writing calibrated tags to library files.

    This service provides methods to apply calibration to files.
    It updates tier and mood tags by applying calibration to raw scores
    already stored in the database, without re-running ML inference.

    Architecture note:
    - Service provides API surface and DI
    - Actual tagging logic lives in workflows/calibration/write_calibrated_tags_wf.py
    - Background execution is managed via BackgroundTaskService (BTS), scoped to this service
    """

    def __init__(
        self,
        database: Database,
        cfg: TaggingServiceConfig,
        bts: BackgroundTaskService,
        config_service: ConfigService,
        library_service: LibraryService | None = None,
    ) -> None:
        """Initialize the tagging service.

        Args:
            database: Database instance for persistence operations
            cfg: Service configuration (models_dir, namespace, etc.)
            bts: BackgroundTaskService for managed background task execution
            config_service: Live configuration provider (for calibrate_heads)
            library_service: LibraryService instance (optional, for library operations)

        """
        self.db = database
        self.cfg = cfg
        self._bts = bts
        self._config_service = config_service
        self.library_service = library_service

        # Background apply state — explicit lifecycle: idle → running → completed/failed
        self._apply_result: ApplyCalibrationResult | None = None
        self._apply_error: Exception | None = None
        self._apply_progress_lock = threading.Lock()
        self._apply_progress: dict[str, Any] = {}

    @property
    def namespace(self) -> str:
        """Get the tag namespace from library service config."""
        if self.library_service is None:
            msg = "LibraryService not configured. Cannot determine namespace."
            raise ValueError(msg)
        return self.library_service.cfg.namespace

    def tag_file(self, file_path: str) -> None:
        """Write calibrated tags to a single file.

        Args:
            file_path: Absolute path to the audio file

        """
        params = WriteCalibratedTagsParams(
            file_path=file_path,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
            version_tag_key=self.cfg.version_tag_key,
            calibrate_heads=self._config_service.get("calibrate_heads", False),
        )

        write_calibrated_tags_wf(db=self.db, params=params)
        logger.info(f"Wrote calibrated tags: {file_path}")

    def tag_library(self) -> ApplyCalibrationResult:
        """Apply calibration to all tagged library files that need it.

        Only processes files whose DB mood tags are stale relative to the
        current calibration version (``meta.calibration_version``).  Files
        whose ``calibration_hash`` already matches are skipped, making this
        operation idempotent.

        When no calibration version exists (first run), all tagged files are
        processed so they receive their initial mood tags.

        Delegates to apply_calibration_wf for the actual iteration.
        Progress updates are forwarded via self._update_apply_progress.

        Returns:
            ApplyCalibrationResult with processed/failed counts

        Raises:
            ValueError: If library_service not configured

        """
        if self.library_service is None:
            msg = "LibraryService not configured. Cannot get library paths."
            raise ValueError(msg)

        # Get tagged files that are not yet calibrated (boolean axis).
        # When no calibration has ever run, all tagged files will be not_calibrated.
        paths = self.library_service.get_paths_needing_calibration()
        if paths:
            logger.info(f"[TaggingService] {len(paths)} files need calibration update")
        else:
            logger.info("[TaggingService] All tagged files are already calibrated")

        return apply_calibration_wf(
            db=self.db,
            paths=paths,
            models_dir=self.cfg.models_dir,
            namespace=self.cfg.namespace,
            version_tag_key=self.cfg.version_tag_key,
            calibrate_heads=self._config_service.get("calibrate_heads", False),
            on_progress=self._update_apply_progress,
        )

    # -- Background apply threading infrastructure --

    def start_apply_calibration_background(self) -> None:
        """Start calibration apply in a managed background task.

        Non-blocking: returns immediately. Poll with is_apply_running() and
        get_apply_combined_status().

        Uses configuration from TaggingServiceConfig for models_dir, namespace, etc.

        Note: Single-process only. Thread state is in-memory and will not survive
        worker restarts, multiple uvicorn workers, or horizontal scaling.

        """
        if self.is_apply_running():
            logger.warning("[TaggingService] Apply already running")
            return

        # Reset state for new run (clears previous completed/failed state)
        self._apply_result = None
        self._apply_error = None
        self._clear_apply_progress()

        task = ManagedTask(
            task_id=CALIBRATION_APPLY_TASK_ID,
            fn=self._run_apply_calibration,
            daemon=False,
        )
        try:
            self._bts.start_task(task)
        except ValueError:
            logger.warning("[TaggingService] Apply already running")
            return

        logger.info("[TaggingService] Started calibration apply in background")

    def _run_apply_calibration(self) -> ApplyCalibrationResult:
        """Managed background task: run calibration apply.

        Progress is NOT cleared on completion — the final snapshot remains queryable
        until the next run starts.
        """
        try:
            logger.info("[TaggingService] Background apply started")
            result = self.tag_library()
            self._apply_result = result
            logger.info(
                f"[TaggingService] Background apply completed: "
                f"{result.processed} processed, {result.failed} failed out of {result.total}",
            )
            return result
        except Exception as e:
            logger.error(f"[TaggingService] Background apply failed: {e}", exc_info=True)
            self._apply_error = e
            raise

    def _update_apply_progress(self, **kwargs: int | str | None) -> None:
        """Thread-safe update of apply progress state.

        Args:
            **kwargs: Progress fields to update. Valid keys:
                completed_files, total_files, current_file

        """
        with self._apply_progress_lock:
            self._apply_progress.update(kwargs)

    def _clear_apply_progress(self) -> None:
        """Reset apply progress state."""
        with self._apply_progress_lock:
            self._apply_progress = {}

    def is_apply_running(self) -> bool:
        """Check if calibration apply is currently running."""
        status = self._bts.get_task_status(CALIBRATION_APPLY_TASK_ID)
        return status is not None and status.get("status") == "running"

    def _get_apply_status(self) -> ApplyCalibrationStatusDict:
        """Get current lifecycle status of background calibration apply.

        Lifecycle: idle → running → completed | failed.
        Status remains queryable after completion until next start clears it.

        Returns:
            {
              "status": "idle" | "running" | "completed" | "failed",
              "result": {"processed": int, "failed": int, "total": int, "message": str} | None,
              "error": str | None,
            }

        """
        running = self.is_apply_running()

        status: Literal["idle", "running", "completed", "failed"]
        if running:
            status = "running"
        elif self._apply_error:
            status = "failed"
        elif self._apply_result:
            status = "completed"
        else:
            status = "idle"

        error = str(self._apply_error) if self._apply_error else None
        result_dict: ApplyCalibrationResultDict | None = None
        if self._apply_result:
            result_dict = {
                "processed": self._apply_result.processed,
                "failed": self._apply_result.failed,
                "total": self._apply_result.total,
                "message": self._apply_result.message,
            }

        return {
            "status": status,
            "result": result_dict,
            "error": error,
        }

    def _get_apply_progress(self) -> ApplyCalibrationProgressDict:
        """Get calibration apply progress.

        Progress snapshot persists after completion until next run.

        Returns:
            {
              "total_files": int,
              "completed_files": int,
              "current_file": str | None,
              "is_running": bool,
            }

        """
        running = self.is_apply_running()
        with self._apply_progress_lock:
            progress = dict(self._apply_progress)

        return {
            "total_files": progress.get("total_files", 0),
            "completed_files": progress.get("completed_files", 0),
            "current_file": progress.get("current_file"),
            "is_running": running,
        }

    def get_apply_combined_status(self) -> ApplyCalibrationCombinedStatusDict:
        """Get combined lifecycle status and per-file progress for apply.

        Returns:
            {
              "status": "idle" | "running" | "completed" | "failed",
              "result": {"processed": int, "failed": int, "total": int, "message": str} | None,
              "error": str | None,
              "total_files": int,
              "completed_files": int,
              "current_file": str | None,
              "is_running": bool,
            }

        """
        status = self._get_apply_status()
        progress = self._get_apply_progress()

        return {
            "status": status["status"],
            "result": status["result"],
            "error": status["error"],
            "total_files": progress["total_files"],
            "completed_files": progress["completed_files"],
            "current_file": progress["current_file"],
            "is_running": progress["is_running"],
        }

    def get_calibration_status(self) -> dict[str, Any]:
        """Get global calibration status with per-library breakdown.

        Returns:
            Dict representation of GlobalCalibrationStatus DTO

        """
        # Get global calibration version from meta
        global_version = self.db.meta.get("calibration_version")
        last_run_str = self.db.meta.get("calibration_last_run")
        last_run = int(last_run_str) if last_run_str else None

        # Get per-library calibration counts
        library_status_list = []
        if global_version and self.library_service:
            # Get library counts
            status_data = self.db.file_states.get_calibration_status_by_library()

            # Enrich with library names
            for status in status_data:
                library_id = status["library_id"]
                library_doc = self.db.libraries.get_library(library_id)

                if library_doc:
                    calibrated = status["calibrated_count"]
                    not_calibrated = status["not_calibrated_count"]
                    total = calibrated + not_calibrated
                    percentage = (calibrated / total * 100) if total > 0 else 0.0

                    library_status_list.append(
                        LibraryCalibrationStatus(
                            library_id=library_id,
                            library_name=library_doc.get("name", "Unknown"),
                            total_files=total,
                            current_count=calibrated,
                            outdated_count=not_calibrated,
                            percentage=round(percentage, 1),
                        ),
                    )

        result = GlobalCalibrationStatus(
            global_version=global_version,
            last_run=last_run,
            libraries=library_status_list,
        )

        # Convert to dict for interface layer
        result_dict: dict[str, Any] = asdict(result)
        return result_dict

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
        library_id: str,
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
            library_id: Library document _id
            batch_size: Number of files to process per batch
            namespace: Tag namespace (default: "nom")

        Returns:
            WriteTagsResult with processed, remaining, and failed counts

        """
        # Get library settings
        library = self.db.libraries.get_library(library_id)
        if not library:
            msg = f"Library not found: {library_id}"
            raise ValueError(msg)

        target_mode = library.get("file_write_mode", "full")
        calibration_hash = self.db.meta.get("calibration_version")
        has_calibration = bool(calibration_hash)

        # Claim files for reconciliation
        worker_id = f"reconcile:{library_id}"
        claimed_files = self.db.library_files.claim_files_for_reconciliation(
            library_id=library_id,
            worker_id=worker_id,
            batch_size=batch_size,
        )

        processed = 0
        failed = 0

        for file_doc in claimed_files:
            file_key = file_doc["_key"]
            try:
                result = write_file_tags_workflow(
                    db=self.db,
                    file_key=file_key,
                    target_mode=target_mode,
                    calibration_hash=calibration_hash,
                    has_calibration=has_calibration,
                    namespace=namespace,
                )
                if result.success:
                    processed += 1
                elif result.error == "file_modified_externally":
                    # File changed on disk since DB was last scanned; release claim
                    # so it can be retried after the scanner updates the mtime.
                    logger.debug(f"[reconcile] Skipping {file_key}: modified externally, will retry after rescan")
                    self.db.library_files.release_claim(file_key)
                else:
                    failed += 1
                    logger.warning(f"[reconcile] Failed to write tags for {file_key}: {result.error}")
            except Exception as e:
                failed += 1
                logger.exception(f"[reconcile] Error processing {file_key}: {e}")
                # Release claim on error
                try:
                    self.db.library_files.release_claim(file_key)
                except Exception as release_err:
                    logger.debug(f"[reconcile] Failed to release claim for {file_key}: {release_err}")

        # Count remaining files needing reconciliation
        remaining = self.db.library_files.count_files_needing_reconciliation(
            library_id=library_id,
        )

        logger.info(f"[reconcile] Library {library_id}: processed={processed}, failed={failed}, remaining={remaining}")

        return WriteTagsResult(
            processed=processed,
            remaining=remaining,
            failed=failed,
        )

    def start_write_tags_background(
        self,
        library_id: str,
        stop_event: threading.Event,
        on_complete: Callable[[], None] | None = None,
    ) -> str:
        """Dispatch a non-blocking background write-tags loop for a library.

        Starts a managed background task that repeatedly calls
        :meth:`write_tags_to_files` for the given library until either all pending
        tag writes have been processed (``remaining == 0``) or ``stop_event`` is
        set.

        Args:
            library_id: Library document _id to write
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

    def mark_tags_stale(self, library_id: str) -> int:
        """Mark all file tags in a library as stale.

        Args:
            library_id: Library document _id

        Returns:
            Number of files marked stale

        """
        return self.db.file_states.bulk_set_tags_stale(library_id)

    def get_reconcile_status(
        self,
        library_id: str,
    ) -> dict[str, Any]:
        """Get reconciliation status for a library.

        Args:
            library_id: Library document _id

        Returns:
            Dict with pending_count and in_progress status

        """
        # Get library settings
        library = self.db.libraries.get_library(library_id)
        if not library:
            msg = f"Library not found: {library_id}"
            raise ValueError(msg)

        pending_count = self.db.library_files.count_files_needing_reconciliation(
            library_id=library_id,
        )
        task_status = self._bts.get_task_status(f"write_tags:{library_id}")
        in_progress = task_status is not None and task_status["status"] == "running"

        return {
            "pending_count": pending_count,
            "in_progress": in_progress,
        }

    # ── Nom-prefix guard ──────────────────────────────────────────────

    @staticmethod
    def _reject_nom_prefix(rel: str | None = None, *, tag_doc: dict[str, Any] | None = None) -> None:
        """Raise ValueError if the tag or rel has the read-only nom: prefix (ADR-009)."""
        if rel is not None and rel.startswith("nom:"):
            msg = f"Tags with 'nom:' prefix are read-only and cannot be edited: rel={rel}"
            raise ValueError(msg)
        if tag_doc is not None and str(tag_doc.get("rel", "")).startswith("nom:"):
            msg = f"Tags with 'nom:' prefix are read-only and cannot be edited: {tag_doc.get('rel')}={tag_doc.get('value')}"
            raise ValueError(msg)

    def _get_tag_or_error(self, tag_id: str) -> dict[str, Any]:
        """Fetch a tag document or raise ValueError."""
        tag = self.db.tags.get_tag(tag_id)
        if not tag:
            msg = f"Tag not found: {tag_id}"
            raise ValueError(msg)
        return tag

    # ── Curation methods (P1-S1) ──────────────────────────────────────

    def rename_tag(self, tag_id: str, new_value: str) -> RenameResult:
        """Rename a tag to a new value.

        Rejects nom: prefix tags (ADR-009). Creates target tag if needed,
        then relinks all edges from source to target.

        Args:
            tag_id: Source tag _id (e.g., "tags/12345")
            new_value: New value for the tag

        Returns:
            RenameResult with moved count and whether it merged into existing

        Raises:
            ValueError: If tag not found or has nom: prefix

        """
        source_tag = self._get_tag_or_error(tag_id)
        self._reject_nom_prefix(tag_doc=source_tag)

        # Find or create target tag with same rel
        target_tag_id = self.db.tags.find_or_create_tag(source_tag["rel"], new_value)
        merged_into_existing = target_tag_id != tag_id

        # Relink all edges from source to target
        relink = self.db.tags.relink_tag_edges(tag_id, target_tag_id)

        # Mark affected files as needing writeback
        song_ids = self.db.tags.list_songs_for_tag(target_tag_id)
        for song_id in song_ids:
            self.db.file_states.set_tags_not_written(song_id)

        return RenameResult(moved=relink["moved"], merged_into_existing=merged_into_existing)

    def merge_tags(self, source_tag_ids: list[str], canonical_tag_id: str) -> MergeResult:
        """Merge multiple source tags into a canonical tag.

        Rejects nom: prefix tags (ADR-009). Iterates each source through
        relink_tag_edges to the canonical target.

        Args:
            source_tag_ids: Tag _ids to merge FROM
            canonical_tag_id: Tag _id to merge INTO

        Returns:
            MergeResult with total_moved and sources_removed counts

        Raises:
            ValueError: If any tag not found or has nom: prefix

        """
        canonical_tag = self._get_tag_or_error(canonical_tag_id)
        self._reject_nom_prefix(tag_doc=canonical_tag)

        total_moved = 0
        sources_removed = 0

        for source_id in source_tag_ids:
            if source_id == canonical_tag_id:
                continue
            source_tag = self._get_tag_or_error(source_id)
            self._reject_nom_prefix(tag_doc=source_tag)

            relink = self.db.tags.relink_tag_edges(source_id, canonical_tag_id)
            total_moved += relink["moved"]
            if relink["source_orphaned"]:
                sources_removed += 1

        # Mark affected files as needing writeback
        song_ids = self.db.tags.list_songs_for_tag(canonical_tag_id)
        for song_id in song_ids:
            self.db.file_states.set_tags_not_written(song_id)

        return MergeResult(total_moved=total_moved, sources_removed=sources_removed)

    def split_tag(self, source_tag_id: str, song_ids: list[str], new_value: str) -> SplitResult:
        """Split selected songs from a tag into a new tag value.

        Rejects nom: prefix tags (ADR-009). Creates a new tag with the given
        value and relinks only the specified songs.

        Args:
            source_tag_id: Tag _id to split FROM
            song_ids: Song _ids to move to the new tag
            new_value: Value for the new tag

        Returns:
            SplitResult with moved count and whether a new tag was created

        Raises:
            ValueError: If tag not found or has nom: prefix

        """
        source_tag = self._get_tag_or_error(source_tag_id)
        self._reject_nom_prefix(tag_doc=source_tag)

        # Find or create target tag with same rel
        target_tag_id = self.db.tags.find_or_create_tag(source_tag["rel"], new_value)
        new_tag_created = target_tag_id != source_tag_id

        # Relink only the specified songs
        relink = self.db.tags.relink_tag_edges(source_tag_id, target_tag_id, song_ids=song_ids)

        # Mark affected files as needing writeback
        for song_id in song_ids:
            self.db.file_states.set_tags_not_written(song_id)

        return SplitResult(moved=relink["moved"], new_tag_created=new_tag_created)

    def update_file_tags(self, file_id: str, rel: str, values: list[str]) -> dict[str, Any]:
        """Replace all tags for a file+rel with new values.

        Rejects nom: prefix rels (ADR-009). Delegates to set_song_tags
        and marks the file for writeback.

        Args:
            file_id: Library file _id
            rel: Tag key (e.g., "genre", "artist")
            values: New tag values

        Returns:
            Dict with updated tags

        Raises:
            ValueError: If rel has nom: prefix

        """
        self._reject_nom_prefix(rel=rel)
        self.db.tags.set_song_tags(file_id, rel, list(values))
        self.db.file_states.set_tags_not_written(file_id)
        # Return current tags for the file
        tags = self.db.tags.get_song_tags(file_id, rel=rel)
        return {"file_id": file_id, "rel": rel, "tags": tags.to_dict()}

    # ── Query methods (P1-S2) ─────────────────────────────────────────

    def list_tag_values(
        self,
        rel: str | None = None,
        prefix: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> TagListResult:
        """List tag values with pagination, optionally filtered by rel and prefix.

        Args:
            rel: Tag rel to filter by (e.g., "genre"). None = all rels.
            prefix: Substring search on tag value.
            limit: Max results per page.
            offset: Pagination offset.

        Returns:
            TagListResult with tags list and total count.

        """
        raw_tags = self.db.tags.list_tags_by_rel(rel=rel, limit=limit, offset=offset, search=prefix)
        total = self.db.tags.count_tags_by_rel(rel=rel, search=prefix)

        tags: list[TagValueItem] = [
            TagValueItem(
                id=t["_id"],
                rel=t["rel"],
                value=str(t["value"]),
                song_count=t.get("song_count", 0),
            )
            for t in raw_tags
        ]
        return TagListResult(tags=tags, total=total)

    def get_tag_songs(
        self,
        tag_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get songs linked to a tag with metadata.

        Args:
            tag_id: Tag _id
            limit: Max results
            offset: Pagination offset

        Returns:
            Dict with songs list and total count.

        """
        raw_songs = self.db.tags.get_tag_songs_with_metadata(tag_id, limit=limit, offset=offset)
        total = self.db.tags.count_songs_for_tag(tag_id)

        songs: list[TagSongItem] = [
            TagSongItem(
                file_id=s["file_id"],
                title=s.get("title", ""),
                artist=s.get("artist", ""),
                album=s.get("album", ""),
                path=s.get("path", ""),
            )
            for s in raw_songs
        ]
        return {"songs": songs, "total": total}

    # ── Commit methods (P1-S3) ────────────────────────────────────────

    def get_pending_commit_count(self) -> int:
        """Count files with pending tag writes (tags_not_written state)."""
        return self.db.file_states.count_pending_tag_writes()

    def commit_pending_tags(self, library_id: str | None = None) -> CommitResult:
        """Commit pending tag writes by writing tags for affected libraries.

        Args:
            library_id: Optional library _id to scope. If None, finds libraries
                        with pending files.

        Returns:
            CommitResult with started flag and pending file count.

        """
        pending = self.db.file_states.count_pending_tag_writes()
        if pending == 0:
            return CommitResult(started=False, pending_files=0)

        if library_id:
            self.write_tags_to_files(library_id)
        else:
            # Write tags for all libraries that have pending files
            libraries = self.db.libraries.list_libraries()
            for lib in libraries:
                self.write_tags_to_files(lib["_id"])

        return CommitResult(started=True, pending_files=pending)

    # ── Migrated tag query methods (P1-S4) ────────────────────────────

    def get_unique_tag_keys(self, nomarr_only: bool = False) -> UniqueTagKeysResult:
        """Get all unique tag keys across the library."""
        keys = get_unique_tag_keys(self.db, nomarr_only)
        return UniqueTagKeysResult(tag_keys=keys, count=len(keys), calibration=None, library_id=None)

    def get_unique_tag_values(self, tag_key: str, nomarr_only: bool = False) -> UniqueTagKeysResult:
        """Get all unique values for a specific tag key."""
        values = get_unique_tag_values(self.db, tag_key, nomarr_only)
        return UniqueTagKeysResult(tag_keys=values, count=len(values), calibration=None, library_id=None)

    def get_unique_mood_values(self, mood_tier: str = "mood-strict", limit: int = 100) -> UniqueTagKeysResult:
        """Get unique individual mood values extracted from tuple string tags."""
        values = self.db.tags.get_unique_mood_values(mood_tier=mood_tier, limit=limit)
        return UniqueTagKeysResult(tag_keys=values, count=len(values), calibration=None, library_id=None)

    def get_file_tags(self, file_id: str, nomarr_only: bool = False) -> FileTagsResult:
        """Get all tags for a specific file.

        Args:
            file_id: Library file ID
            nomarr_only: If True, only return Nomarr-generated tags

        Returns:
            FileTagsResult DTO with file info and tags

        Raises:
            ValueError: If file not found

        """
        result = get_file_tags_with_path(self.db, file_id, nomarr_only=nomarr_only)
        if not result:
            msg = f"File with ID {file_id} not found"
            raise ValueError(msg)

        tags = [
            FileTag(
                key=tag["key"],
                value=str(tag["value"]),
                tag_type=tag["type"],
                is_nomarr=tag["is_nomarr_tag"],
            )
            for tag in result["tags"]
        ]

        return FileTagsResult(
            file_id=file_id,
            path=result["path"],
            tags=tags,
        )

    def cleanup_orphaned_tags(self, dry_run: bool = False) -> TagCleanupResult:
        """Clean up orphaned tags from the database.

        Args:
            dry_run: If True, count orphaned tags but don't delete them

        Returns:
            TagCleanupResult DTO with orphaned_count and deleted_count

        """
        result = cleanup_orphaned_tags_workflow(self.db, dry_run=dry_run)
        return TagCleanupResult(
            orphaned_count=result["orphaned_count"],
            deleted_count=result["deleted_count"],
        )

    def search_files_by_tag(
        self,
        tag_key: str,
        target_value: float | str,
        limit: int = 100,
        offset: int = 0,
    ) -> SearchFilesResult:
        """Search files by tag value with distance sorting (float) or exact match (string).

        Args:
            tag_key: Tag key to search (e.g., "nom:bpm", "genre")
            target_value: Target value (float for distance sort, string for exact match)
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            SearchFilesResult with matched files

        """
        files = self.db.library_files.search_files_by_tag(tag_key, target_value, limit, offset)
        total = self.db.library_files.count_files_by_tag(tag_key, target_value)
        files_with_tags = [map_file_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(files=files_with_tags, total=total, limit=limit, offset=offset)
