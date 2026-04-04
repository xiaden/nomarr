"""Validate and heal DB state for unchanged files during full scan.

During a full scan, files whose mtime hasn't changed are skipped for performance.
However, their edge state may be missing (e.g., short files that should have an
``ml_tagged`` edge with version="scan_skipped" but don't). This component
validates and heals such cases.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


@dataclass
class ValidationStats:
    """Statistics from validating unchanged files."""

    files_checked: int = 0
    short_files_healed: int = 0


def validate_unchanged_files(
    db: Database,
    library_id: str,
    min_duration_s: int,
) -> ValidationStats:
    """Validate and heal edge state for unchanged files in a library.

    Currently handles:
    - Short files without ml_tagged edge → create edge with version="scan_skipped"

    Args:
        db: Database instance
        library_id: Library document _id
        min_duration_s: Minimum duration for ML tagging (files shorter are skipped)

    Returns:
        ValidationStats with counts of checked and healed files

    """
    stats = ValidationStats()

    short_healed = _heal_short_files(db, library_id, min_duration_s)
    stats.short_files_healed = short_healed
    stats.files_checked = short_healed

    if short_healed > 0:
        logger.info(
            "[validate_scan_state] Healed %d short files (duration < %ds) in library %s",
            short_healed,
            min_duration_s,
            library_id,
        )

    return stats


def _heal_short_files(
    db: Database,
    library_id: str,
    min_duration_s: int,
) -> int:
    """Find and heal short files without too_short state.

    Sets ``too_short`` state for short files that don't already have it.

    Args:
        db: Database instance
        library_id: Library document _id
        min_duration_s: Files with duration_seconds < this are "short"

    Returns:
        Number of files healed

    """
    # Find short files missing too_short state
    cursor = db.db.aql.execute(
        """
        FOR file IN library_files
            FILTER file.library_id == @library_id
            FILTER file.duration_seconds != null
            FILTER file.duration_seconds < @min_duration_s
            LET has_too_short = LENGTH(
                FOR edge IN file_has_state
                    FILTER edge._from == file._id AND edge._to == "file_states/too_short"
                    LIMIT 1
                    RETURN 1
            )
            FILTER has_too_short == 0
            RETURN file._id
        """,
        bind_vars={
            "library_id": library_id,
            "min_duration_s": min_duration_s,
        },
    )

    file_ids = list(cursor)
    for file_id in file_ids:
        db.file_states.set_too_short(file_id)

    return len(file_ids)
