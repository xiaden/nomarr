"""Load calibrations from database for tag computation.

ARCHITECTURE:
- This is a WORKFLOW function that queries calibration_state
- Calibration semantics (p5/p95 interpretation) live here, not in components
- Used by both initial processing and recalibration workflows

DEPENDENCIES:
- db: Database instance with calibration_state accessor
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.ml.calibration.ml_calibration_state_comp import load_all_calibration_states

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


def load_calibrations_from_db_wf(db: Database) -> dict[str, dict[str, Any]]:
    """Load all calibrations from calibration_state collection.

    Returns dict mapping label -> {p5, p95} for use in aggregation.
    Format matches legacy sidecar structure for compatibility with aggregation logic.

    Args:
        db: Database instance

    Returns:
        Dict mapping label (e.g., "happy") to {p5: float, p95: float}
        Empty dict if no calibrations exist (initial state before first generation)

    Example:
        {
            "happy": {"p5": 0.123, "p95": 0.876, "calibration_def_hash": "b539fc8a..."},
            "sad": {"p5": 0.100, "p95": 0.900, "calibration_def_hash": "a1b2c3d4..."}
        }

    Note:
        If no calibrations exist, aggregation will use raw scores without normalization.
        This is expected behavior during initial library setup.

    """
    try:
        calibration_states = load_all_calibration_states(db)

        if not calibration_states:
            logger.debug("[calibration_loader] No calibrations in database (initial state)")
            return {}

        # Build lookup by label (the actual label field from calibration_state)
        calibrations: dict[str, dict[str, Any]] = {}

        for state in calibration_states:
            label = state.get("label")
            p5 = state.get("p5")
            p95 = state.get("p95")
            calib_hash = state.get("calibration_def_hash")

            if label and p5 is not None and p95 is not None:
                calibrations[label] = {"p5": p5, "p95": p95, "calibration_def_hash": calib_hash}

        logger.info(f"[calibration_loader] Loaded {len(calibrations)} calibrations from database")
        return calibrations

    except Exception as e:
        logger.exception(f"[calibration_loader] Failed to load calibrations: {e}")
        return {}


# Module-level cache for calibrations
_cached_calibrations: dict[str, dict[str, float]] | None = None
_cached_version: str | None = None


def load_calibrations_cached_wf(db: Database) -> dict[str, dict[str, float]]:
    """Load calibrations with caching based on version hash.

    Checks calibration_version in meta collection. If version matches cached
    version, returns cached calibrations without database query.

    Cache is module-level (per-process), so workers maintain separate caches.
    Version check is ~2-5ms single document lookup vs ~50ms full calibration load.

    Args:
        db: Database instance

    Returns:
        Dict mapping label to {p5, p95}
        Empty dict if no calibrations exist

    Note:
        When calibration generation completes, it updates calibration_version in meta,
        causing cache invalidation on next check.

    """
    from nomarr.components.ml.calibration.ml_calibration_state_comp import get_calibration_version

    global _cached_calibrations, _cached_version

    # Check current version (cheap: single doc lookup)
    current_version = get_calibration_version(db)

    # Cache miss or version changed - reload calibrations
    if _cached_version != current_version:
        _cached_calibrations = load_calibrations_from_db_wf(db)
        _cached_version = current_version

        if current_version:
            logger.info(
                f"[calibration_loader] Loaded calibrations version {current_version[:12]}... "
                f"({len(_cached_calibrations)} labels)"
            )
        else:
            logger.debug("[calibration_loader] No calibration version set (initial state)")

    return _cached_calibrations or {}
