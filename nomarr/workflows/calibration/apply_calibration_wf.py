"""Apply calibration to all tagged library files."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Protocol

from nomarr.helpers.dto.calibration_dto import WriteCalibratedTagsParams
from nomarr.helpers.dto.recalibration_dto import ApplyCalibrationResult
from nomarr.helpers.time_helper import internal_ms
from nomarr.workflows.calibration.write_calibrated_tags_wf import write_calibrated_tags_wf

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


class ApplyProgressCallback(Protocol):
    """Callback protocol for reporting apply-calibration progress."""

    def __call__(
        self,
        *,
        completed_files: int,
        total_files: int,
        current_file: str,
    ) -> None: ...


def apply_calibration_wf(
    *,
    db: Database,
    paths: list[str],
    models_dir: str,
    namespace: str,
    version_tag_key: str,
    calibrate_heads: bool,
    on_progress: ApplyProgressCallback | None = None,
    max_write_workers: int = 4,
) -> ApplyCalibrationResult:
    """Apply calibration to all tagged library files.

    Iterates over every file path, applies calibrated tags via
    write_calibrated_tags_wf, and tracks success/failure counts.

    Pre-computes invariant data (heads, calibrations, library roots) once
    before the loop to avoid redundant DB queries and filesystem scans.

    File writes execute concurrently via a ThreadPoolExecutor (default 4 workers).

    Args:
        db: Database instance for persistence operations
        paths: List of absolute paths to tagged audio files
        models_dir: Path to ML models directory
        namespace: Tag namespace (e.g., "nom")
        version_tag_key: Metadata key for version tracking
        calibrate_heads: Whether to apply calibration heads
        on_progress: Optional callback invoked after each file
        max_write_workers: Max concurrent file write workers (default 4)

    Returns:
        ApplyCalibrationResult with processed/failed/total counts

    """
    import os
    from pathlib import Path

    from nomarr.components.library.scan_lifecycle_comp import save_folder_record
    from nomarr.components.ml.calibration_state_comp import get_calibration_version
    from nomarr.components.ml.ml_discovery_comp import discover_heads
    from nomarr.components.tagging.tagging_writer_comp import TagWriter
    from nomarr.helpers.files_helper import is_audio_file
    from nomarr.workflows.calibration.calibration_loader_wf import load_calibrations_from_db_wf
    from nomarr.workflows.calibration.write_calibrated_tags_wf import BatchContext

    total = len(paths)
    if not paths:
        return ApplyCalibrationResult(
            processed=0,
            failed=0,
            total=0,
            message="No tagged files found. Run tagging first.",
        )

    logger.info(f"Writing calibrated tags to {total} files...")

    # Pre-compute all invariants once (instead of per-file)
    _t0 = internal_ms()
    logger.info("[apply_calibration] Pre-computing batch context...")
    heads = discover_heads(models_dir)
    calibrations = load_calibrations_from_db_wf(db)
    calibration_version = get_calibration_version(db)

    # Pre-resolve library roots (one DB query instead of N)
    libraries = db.libraries.list_libraries()
    library_roots: dict[str, Path] = {}
    for lib in libraries:
        library_roots[lib["_id"]] = Path(lib["root_path"]).resolve()

    writer = TagWriter(overwrite=True, namespace=namespace)

    batch_ctx = BatchContext(
        heads=heads,
        calibrations=calibrations,
        calibration_version=calibration_version,
        library_roots=library_roots,
        writer=writer,
    )

    # --- Bulk prefetch DB data for all files ---
    _t_prefetch_start = internal_ms()
    logger.info(f"[apply_calibration] Bulk prefetching DB data for {total} files...")
    prefetched_file_docs = db.library_files.get_files_by_paths_bulk(paths)
    # Collect file_ids for tag and stats prefetch
    all_file_ids = [doc["_id"] for doc in prefetched_file_docs.values()]
    prefetched_tags = db.tags.get_nomarr_tags_bulk(all_file_ids) if all_file_ids else {}
    prefetched_stats = db.segment_scores_stats.get_stats_for_files_bulk(all_file_ids) if all_file_ids else {}

    batch_ctx.prefetched_file_docs = prefetched_file_docs
    batch_ctx.prefetched_tags = prefetched_tags
    batch_ctx.prefetched_stats = prefetched_stats

    logger.info(
        f"[apply_calibration] Batch context ready: {len(heads)} heads, "
        f"{len(calibrations)} calibrations, {len(library_roots)} libraries, "
        f"{len(prefetched_file_docs)}/{total} files cached"
    )
    _t_prefetch = (internal_ms().value - _t_prefetch_start.value) / 1000
    _t_setup = (internal_ms().value - _t0.value) / 1000
    logger.info(
        f"[apply_calibration] Setup complete in {_t_setup:.2f}s "
        f"(prefetch: {_t_prefetch:.2f}s)"
    )

    success_count = 0
    fail_count = 0
    completed_lock = threading.Lock()
    completed_count = [0]

    def _process_file(file_path: str, idx: int) -> bool:
        """Process a single file (runs in thread pool)."""
        try:
            params = WriteCalibratedTagsParams(
                file_path=file_path,
                models_dir=models_dir,
                namespace=namespace,
                version_tag_key=version_tag_key,
                calibrate_heads=calibrate_heads,
            )
            write_calibrated_tags_wf(db=db, params=params, batch_ctx=batch_ctx)
            return True
        except Exception as e:
            logger.warning(f"Failed to write calibrated tags for {file_path}: {e}")
            return False

    # Step: submit file writes to thread pool
    _t_io_start = internal_ms()
    futures_map = {}
    with ThreadPoolExecutor(max_workers=max_write_workers) as executor:
        for i, file_path in enumerate(paths):
            fut = executor.submit(_process_file, file_path, i)
            futures_map[fut] = (i, file_path)

        for fut in as_completed(futures_map):
            i, file_path = futures_map[fut]
            ok = fut.result()  # exceptions already caught inside _process_file
            if ok:
                success_count += 1
            else:
                fail_count += 1
            with completed_lock:
                completed_count[0] += 1
                done_so_far = completed_count[0]
            if on_progress is not None:
                on_progress(
                    completed_files=done_so_far,
                    total_files=total,
                    current_file=file_path,
                )

    _t_io = (internal_ms().value - _t_io_start.value) / 1000
    logger.info(
        f"[apply_calibration] File I/O complete in {_t_io:.2f}s "
        f"({max_write_workers} workers, {total} files)"
    )

    # Step: batch-update folder mtimes (once per unique folder)
    _t_postprocess_start = internal_ms()
    pending = batch_ctx.pending_folders
    if pending:
        logger.info(f"[apply_calibration] Updating {len(pending)} folder mtime records...")
        for folder_str, (library_id, library_root) in pending.items():
            try:
                folder_abs = Path(folder_str)
                folder_mtime = int(os.stat(folder_abs).st_mtime * 1000)
                folder_rel = str(folder_abs.relative_to(library_root)).replace("\\", "/")
                if folder_abs == library_root:
                    folder_rel = ""
                file_count = sum(
                    1 for f in os.listdir(folder_abs)
                    if is_audio_file(f) and os.path.isfile(os.path.join(folder_abs, f))
                )
                save_folder_record(db, library_id, folder_rel, folder_mtime, file_count)
            except Exception as e:
                logger.warning(f"[apply_calibration] Failed to update folder mtime for {folder_str}: {e}")

    # Step: flush deferred DB writes in bulk (3 AQL queries regardless of file count)
    from nomarr.components.ml.calibration_state_comp import update_file_calibration_hashes_batch
    from nomarr.components.processing.file_write_comp import save_mood_tags_batch

    if batch_ctx.pending_mood_tags:
        logger.info(f"[apply_calibration] Flushing {len(batch_ctx.pending_mood_tags)} mood tag writes...")
        try:
            save_mood_tags_batch(db, batch_ctx.pending_mood_tags)
        except Exception as e:
            logger.warning(f"[apply_calibration] Batch mood tag flush failed: {e}")

    if batch_ctx.pending_calibration_hashes:
        logger.info(f"[apply_calibration] Flushing {len(batch_ctx.pending_calibration_hashes)} calibration hash updates...")
        try:
            update_file_calibration_hashes_batch(db, batch_ctx.pending_calibration_hashes)
        except Exception as e:
            logger.warning(f"[apply_calibration] Batch calibration hash flush failed: {e}")

    _t_postprocess = (internal_ms().value - _t_postprocess_start.value) / 1000
    _t_total = (internal_ms().value - _t0.value) / 1000
    logger.info(
        f"[apply_calibration] DONE in {_t_total:.2f}s — "
        f"setup={_t_setup:.2f}s prefetch={_t_prefetch:.2f}s "
        f"io={_t_io:.2f}s postprocess={_t_postprocess:.2f}s | "
        f"{success_count}/{total} ok, {fail_count} failed"
    )
    logger.info(f"Wrote calibrated tags: {success_count}/{total} files ({fail_count} failed)")

    return ApplyCalibrationResult(
        processed=success_count,
        failed=fail_count,
        total=total,
        message=f"Wrote calibrated tags to {success_count}/{total} files",
    )
