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

from nomarr.components.library.library_file_state_comp import (
    find_short_files_missing_too_short,
    transition_file_state,
)
from nomarr.helpers.constants.file_states import STATE_NOT_TOO_SHORT, STATE_TOO_SHORT

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
        library_id: Library document ``_id``; files are sourced via OUTBOUND
            edge traversal on ``library_contains_file``.
        min_duration_s: Files with duration_seconds < this are "short"

    Returns:
        Number of files healed

    """
    file_ids = find_short_files_missing_too_short(db, library_id, min_duration_s)
    for file_id in file_ids:
        transition_file_state(db, [file_id], STATE_NOT_TOO_SHORT, STATE_TOO_SHORT)

    return len(file_ids)
