"""Validate and heal DB state for unchanged files during full scan.

During a full scan, files whose mtime hasn't changed are skipped for performance.
However, their DB state may be stale (e.g., needs_tagging=true for short files
that should be marked skipped). This component validates and heals such cases.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

# Batch size for DB operations (balance memory vs round-trips)
_BATCH_SIZE = 1000


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
    """Validate and heal DB state for unchanged files in a library.

    Currently handles:
    - Short files with needs_tagging=true → heal to needs_tagging=false

    Args:
        db: Database instance
        library_id: Library document _id
        min_duration_s: Minimum duration for ML tagging (files shorter are skipped)

    Returns:
        ValidationStats with counts of checked and healed files

    """
    stats = ValidationStats()

    # Find and heal short files that still have needs_tagging=true
    # This happens for files scanned before the short-file filter was added
    short_healed = _heal_short_files(db, library_id, min_duration_s)
    stats.short_files_healed = short_healed

    # Count total unchanged files that were checked
    # (For now, just the short file check - can expand later)
    stats.files_checked = short_healed  # Only checked files that needed healing

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
    """Find and heal short files with stale needs_tagging=true.

    Args:
        db: Database instance
        library_id: Library document _id
        min_duration_s: Files with duration_seconds < this are "short"

    Returns:
        Number of files healed

    """
    # Single query to find and update short files
    # This is efficient because:
    # 1. Uses index on library_id + needs_tagging
    # 2. Only touches files that actually need healing
    # 3. Single round-trip for the update
    query = """
    FOR file IN library_files
        FILTER file.library_id == @library_id
        FILTER file.needs_tagging == true
        FILTER file.is_valid == true
        FILTER file.duration_seconds != null
        FILTER file.duration_seconds < @min_duration_s
        UPDATE file WITH {
            needs_tagging: false,
            tagging_skipped_reason: "too_short"
        } IN library_files
        RETURN 1
    """

    cursor = cast(
        "Cursor",
        db.db.aql.execute(
            query,
            bind_vars={
                "library_id": library_id,
                "min_duration_s": min_duration_s,
            },
        ),
    )

    # Count results (each updated doc returns 1)
    return sum(1 for _ in cursor)
