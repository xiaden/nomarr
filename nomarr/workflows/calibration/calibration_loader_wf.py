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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


def load_calibrations_from_db_wf(db: Database) -> dict[str, dict[str, float]]:
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
            "happy": {"p5": 0.123, "p95": 0.876},
            "sad": {"p5": 0.100, "p95": 0.900}
        }

    Note:
        If no calibrations exist, aggregation will use raw scores without normalization.
        This is expected behavior during initial library setup.

    """
    try:
        calibration_states = db.calibration_state.get_all_calibration_states()

        if not calibration_states:
            logger.debug("[calibration_loader] No calibrations in database (initial state)")
            return {}

        # Build lookup by head_name (label)
        calibrations: dict[str, dict[str, float]] = {}

        for state in calibration_states:
            head_name = state.get("head_name")
            p5 = state.get("p5")
            p95 = state.get("p95")

            if head_name and p5 is not None and p95 is not None:
                # Extract label from head_name
                # e.g., "mood_happy" -> "happy"
                label = head_name.replace("mood_", "").replace("_", " ")
                calibrations[label] = {"p5": p5, "p95": p95}

        logger.info(f"[calibration_loader] Loaded {len(calibrations)} calibrations from database")
        return calibrations

    except Exception as e:
        logger.exception(f"[calibration_loader] Failed to load calibrations: {e}")
        return {}
