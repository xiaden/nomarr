"""Apply calibration to all tagged library files."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from nomarr.helpers.dto.calibration_dto import WriteCalibratedTagsParams
from nomarr.helpers.dto.recalibration_dto import ApplyCalibrationResult
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
) -> ApplyCalibrationResult:
    """Apply calibration to all tagged library files.

    Iterates over every file path, applies calibrated tags via
    write_calibrated_tags_wf, and tracks success/failure counts.

    Pre-computes invariant data (heads, calibrations, library roots) once
    before the loop to avoid redundant DB queries and filesystem scans.

    Args:
        db: Database instance for persistence operations
        paths: List of absolute paths to tagged audio files
        models_dir: Path to ML models directory
        namespace: Tag namespace (e.g., "nom")
        version_tag_key: Metadata key for version tracking
        calibrate_heads: Whether to apply calibration heads
        on_progress: Optional callback invoked after each file

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
    logger.info(
        f"[apply_calibration] Batch context ready: {len(heads)} heads, "
        f"{len(calibrations)} calibrations, {len(library_roots)} libraries"
    )

    success_count = 0
    fail_count = 0

    # Step: iterate files and apply calibrated tags
    for i, file_path in enumerate(paths):
        try:
            params = WriteCalibratedTagsParams(
                file_path=file_path,
                models_dir=models_dir,
                namespace=namespace,
                version_tag_key=version_tag_key,
                calibrate_heads=calibrate_heads,
            )
            write_calibrated_tags_wf(db=db, params=params, batch_ctx=batch_ctx)
            success_count += 1
        except Exception as e:
            fail_count += 1
            logger.warning(f"Failed to write calibrated tags for {file_path}: {e}")

        # Step: report progress to caller
        if on_progress is not None:
            on_progress(
                completed_files=i + 1,
                total_files=total,
                current_file=file_path,
            )

    # Step: batch-update folder mtimes (once per unique folder)
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

    logger.info(f"Wrote calibrated tags: {success_count}/{total} files ({fail_count} failed)")

    return ApplyCalibrationResult(
        processed=success_count,
        failed=fail_count,
        total=total,
        message=f"Wrote calibrated tags to {success_count}/{total} files",
    )
