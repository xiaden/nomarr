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
    total = len(paths)
    if not paths:
        return ApplyCalibrationResult(
            processed=0,
            failed=0,
            total=0,
            message="No tagged files found. Run tagging first.",
        )

    logger.info(f"Writing calibrated tags to {total} files...")

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
            write_calibrated_tags_wf(db=db, params=params)
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

    logger.info(f"Wrote calibrated tags: {success_count}/{total} files ({fail_count} failed)")

    return ApplyCalibrationResult(
        processed=success_count,
        failed=fail_count,
        total=total,
        message=f"Wrote calibrated tags to {success_count}/{total} files",
    )
