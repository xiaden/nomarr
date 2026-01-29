"""Backfill calibration_hash for existing files.

Migration workflow to set calibration_hash on files currently missing it.

ARCHITECTURE:
- This is a WORKFLOW that orchestrates database updates
- Called once during migration from old system to new system
- Should not be needed after migration is complete

STRATEGY:
- Files with NULL calibration_hash were processed before hash tracking existed
- Two options:
  1. Leave as NULL (indicates "never recalibrated", user must recalibrate)
  2. Set to current global hash (assumes files current, risky if calibration changed)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


def backfill_calibration_hashes_wf(
    db: Database,
    set_to_current: bool = False,
) -> dict[str, Any]:
    """Backfill calibration_hash for all files missing it.

    Two strategies available:

    1. Leave as NULL (set_to_current=False, default):
       - Files remain NULL
       - Status queries show as "outdated"
       - User must explicitly recalibrate
       - SAFER: No assumptions about file state

    2. Set to current hash (set_to_current=True):
       - Sets calibration_hash to current global version
       - Assumes files were processed with current calibration
       - Status queries show as "current"
       - RISKY: Wrong if calibration changed since processing

    Args:
        db: Database instance
        set_to_current: If True, set to current global hash; if False, leave NULL

    Returns:
        {
            "files_updated": int (0 if leaving NULL),
            "strategy": "left_null" | "set_to_current",
            "global_version": str | None,
        }

    """
    logger.info("[backfill] Starting calibration_hash backfill analysis...")

    # Get current global version
    global_version = db.meta.get("calibration_version")

    if not global_version:
        logger.warning("[backfill] No global calibration version exists yet")
        return {
            "files_updated": 0,
            "strategy": "skipped_no_version",
            "global_version": None,
        }

    # Count files with NULL calibration_hash
    count_query = """
        FOR f IN library_files
            FILTER f.calibration_hash == null
            COLLECT WITH COUNT INTO count
            RETURN count
    """

    cursor = cast("Cursor", db.db.aql.execute(count_query))
    null_count = next(cursor, 0)

    logger.info(f"[backfill] Found {null_count} files with NULL calibration_hash")

    if null_count == 0:
        return {
            "files_updated": 0,
            "strategy": "none_needed",
            "global_version": global_version,
        }

    if not set_to_current:
        # Strategy 1: Leave as NULL (no updates needed)
        logger.info("[backfill] Leaving files as NULL (safer option)")
        logger.info("[backfill] Files will show as 'outdated' in status queries")
        logger.info("[backfill] Users must explicitly recalibrate to mark as current")
        return {
            "files_updated": 0,
            "strategy": "left_null",
            "global_version": global_version,
            "null_count": null_count,
        }

    # Strategy 2: Set to current hash (risky)
    logger.warning("[backfill] Setting all NULL files to CURRENT hash (risky)")
    logger.warning(f"[backfill] Assuming files processed with current calibration: {global_version[:12]}...")

    # Update all NULL files to current hash
    update_query = """
        FOR f IN library_files
            FILTER f.calibration_hash == null
            UPDATE f WITH { calibration_hash: @hash } IN library_files
            COLLECT WITH COUNT INTO updated
            RETURN updated
    """

    cursor = cast("Cursor", db.db.aql.execute(update_query, bind_vars={"hash": global_version}))
    updated_count = next(cursor, 0)

    logger.info(f"[backfill] Backfill complete: {updated_count} files updated to current hash")

    return {
        "files_updated": updated_count,
        "strategy": "set_to_current",
        "global_version": global_version,
    }
