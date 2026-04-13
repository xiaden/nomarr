"""Apply calibration to all tagged library files."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Protocol

from nomarr.components.library.library_file_query_comp import get_files_by_paths_bulk
from nomarr.components.ml.inference.ml_segment_stats_store_comp import get_segment_stats_for_files_bulk
from nomarr.components.tagging.tag_query_comp import get_nomarr_tags_bulk
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
    prefetch_chunk_size: int = 1000,
) -> ApplyCalibrationResult:
    """Apply calibration to all tagged library files.

    Iterates over every file path, applies calibrated tags via
    write_calibrated_tags_wf, and tracks success/failure counts.

    Pre-computes invariant data (heads, calibrations, library roots) once
    before the loop to avoid redundant DB queries and filesystem scans.

    File writes execute concurrently via a ThreadPoolExecutor (default 4 workers).

    Paths are processed in chunks of `prefetch_chunk_size` (default 1000) to
    bound peak RAM usage. Each chunk prefetches its DB data, processes files,
    flushes deferred writes, and releases the prefetched data before the next
    chunk begins. Invariant data (heads, calibrations, library roots) is held
    across all chunks since it is small.

    Args:
        db: Database instance for persistence operations
        paths: List of absolute paths to tagged audio files
        models_dir: Path to ML models directory
        namespace: Tag namespace (e.g., "nom")
        version_tag_key: Metadata key for version tracking
        calibrate_heads: Whether to apply calibration heads
        on_progress: Optional callback invoked after each file
        max_write_workers: Max concurrent file write workers (default 4)
        prefetch_chunk_size: Number of files to prefetch per batch (default 1000).
            Lower values reduce peak RAM at the cost of more DB round-trips.

    Returns:
        ApplyCalibrationResult with processed/failed/total counts

    """
    import math

    from nomarr.components.ml.calibration.ml_calibration_state_comp import (
        get_calibration_version,
        update_file_calibration_hashes_batch,
    )
    from nomarr.components.ml.onnx.ml_discovery_comp import discover_heads
    from nomarr.components.processing.file_write_comp import save_mood_tags_batch
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

    # --- Pre-compute small invariants once (cheap, shared across all chunks) ---
    _t0 = internal_ms()
    logger.info("[apply_calibration] Pre-computing batch context...")
    heads = discover_heads(models_dir, db)
    calibrations = load_calibrations_from_db_wf(db)
    calibration_version = get_calibration_version(db)

    _t_setup = (internal_ms().value - _t0.value) / 1000
    n_chunks = math.ceil(total / prefetch_chunk_size)
    logger.info(
        f"[apply_calibration] Setup complete in {_t_setup:.2f}s — "
        f"{total} files in {n_chunks} chunk(s) of {prefetch_chunk_size}"
    )

    def _process_file(file_path: str, ctx: BatchContext) -> bool:
        """Process a single file (runs in thread pool)."""
        try:
            params = WriteCalibratedTagsParams(
                file_path=file_path,
                models_dir=models_dir,
                namespace=namespace,
                version_tag_key=version_tag_key,
                calibrate_heads=calibrate_heads,
            )
            write_calibrated_tags_wf(db=db, params=params, batch_ctx=ctx)
            return True
        except Exception as e:
            logger.warning(f"Failed to write calibrated tags for {file_path}: {e}")
            return False

    # --- Chunk loop: prefetch → process → flush → discard ---
    success_count = 0
    fail_count = 0
    completed_count = [0]
    completed_lock = threading.Lock()

    _t_io_total = 0.0
    _t_prefetch_total = 0.0

    for chunk_start in range(0, total, prefetch_chunk_size):
        chunk_paths = paths[chunk_start : chunk_start + prefetch_chunk_size]
        chunk_num = chunk_start // prefetch_chunk_size + 1
        chunk_size = len(chunk_paths)

        # Prefetch DB data for this chunk only
        _t_prefetch_start = internal_ms()
        logger.info(f"[apply_calibration] Chunk {chunk_num}/{n_chunks}: prefetching DB data for {chunk_size} files...")
        prefetched_file_docs = get_files_by_paths_bulk(db, chunk_paths)
        all_file_ids = [doc["_id"] for doc in prefetched_file_docs.values()]
        prefetched_tags = get_nomarr_tags_bulk(db, all_file_ids) if all_file_ids else {}
        prefetched_stats = get_segment_stats_for_files_bulk(db, all_file_ids) if all_file_ids else {}
        _t_prefetch_chunk = (internal_ms().value - _t_prefetch_start.value) / 1000
        _t_prefetch_total += _t_prefetch_chunk

        batch_ctx = BatchContext(
            heads=heads,
            calibrations=calibrations,
            calibration_version=calibration_version,
        )
        batch_ctx.prefetched_file_docs = prefetched_file_docs
        batch_ctx.prefetched_tags = prefetched_tags
        batch_ctx.prefetched_stats = prefetched_stats

        logger.debug(
            f"[apply_calibration] Chunk {chunk_num}/{n_chunks} prefetch done in "
            f"{_t_prefetch_chunk:.2f}s: {len(prefetched_file_docs)}/{chunk_size} files cached"
        )

        _t_io_start = internal_ms()
        futures_map = {}
        with ThreadPoolExecutor(max_workers=max_write_workers) as executor:
            for file_path in chunk_paths:
                fut = executor.submit(_process_file, file_path, batch_ctx)
                futures_map[fut] = file_path

            for fut in as_completed(futures_map):
                file_path = futures_map[fut]
                ok = fut.result()
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

        _t_io_chunk = (internal_ms().value - _t_io_start.value) / 1000
        _t_io_total += _t_io_chunk

        # Flush deferred DB writes for this chunk, then release the cache
        if batch_ctx.pending_mood_tags:
            logger.debug(
                f"[apply_calibration] Chunk {chunk_num}/{n_chunks}: "
                f"flushing {len(batch_ctx.pending_mood_tags)} mood tag writes..."
            )
            try:
                save_mood_tags_batch(db, batch_ctx.pending_mood_tags)
            except Exception as e:
                logger.warning(f"[apply_calibration] Batch mood tag flush failed: {e}")

        if batch_ctx.pending_calibration_hashes:
            logger.debug(
                f"[apply_calibration] Chunk {chunk_num}/{n_chunks}: "
                f"flushing {len(batch_ctx.pending_calibration_hashes)} calibration hash updates..."
            )
            try:
                update_file_calibration_hashes_batch(db, batch_ctx.pending_calibration_hashes)
            except Exception as e:
                logger.warning(f"[apply_calibration] Batch calibration hash flush failed: {e}")

        # Explicitly release prefetched data so GC can reclaim RAM before next chunk
        batch_ctx.prefetched_file_docs = None
        batch_ctx.prefetched_tags = None
        batch_ctx.prefetched_stats = None

        logger.debug(f"[apply_calibration] Chunk {chunk_num}/{n_chunks} done in {_t_io_chunk:.2f}s I/O")

    _t_total = (internal_ms().value - _t0.value) / 1000
    logger.info(
        f"[apply_calibration] DONE in {_t_total:.2f}s — "
        f"setup={_t_setup:.2f}s prefetch={_t_prefetch_total:.2f}s "
        f"io={_t_io_total:.2f}s | "
        f"{success_count}/{total} ok, {fail_count} failed"
    )
    logger.info(f"Applied calibration to DB: {success_count}/{total} files ({fail_count} failed)")

    return ApplyCalibrationResult(
        processed=success_count,
        failed=fail_count,
        total=total,
        message=f"Wrote calibrated tags to {success_count}/{total} files",
    )
