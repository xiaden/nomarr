"""Workflow: assemble global calibration status with per-library breakdown."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.components.library.library_file_state_comp import get_calibration_status_by_library
from nomarr.components.library.library_records_comp import get_library_record
from nomarr.components.ml.calibration.ml_calibration_state_comp import (
    get_calibration_last_run,
    get_calibration_version,
)
from nomarr.helpers.dto.calibration_dto import GlobalCalibrationStatus, LibraryCalibrationStatus

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def get_calibration_status_workflow(db: Database) -> GlobalCalibrationStatus:
    """Return global calibration status with per-library breakdown.

    Args:
        db: Database instance

    Returns:
        GlobalCalibrationStatus DTO with version, last-run timestamp, and
        per-library calibrated/outdated counts.

    """
    # Step 1: Read global calibration metadata
    global_version = get_calibration_version(db)
    last_run = get_calibration_last_run(db)

    # Step 2: Compute per-library breakdown if calibration has run
    library_status_list: list[LibraryCalibrationStatus] = []
    if global_version:
        status_data = get_calibration_status_by_library(db)
        for status in status_data:
            library_id = status["library_id"]
            library_doc = get_library_record(db, library_id, include_scan=False)
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
                    )
                )

    return GlobalCalibrationStatus(
        global_version=global_version,
        last_run=last_run,
        libraries=library_status_list,
    )
