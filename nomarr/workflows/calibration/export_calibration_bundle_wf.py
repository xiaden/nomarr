"""Export calibration data from database to bundle files.

ARCHITECTURE:
- Database (calibration_state) is the SINGLE SOURCE OF TRUTH
- Bundles are TRANSPORT ARTIFACTS for distribution
- This workflow reads calibration_state → emits JSON bundle

USAGE:
- Generate bundle files for nom-cal repository
- Share calibrations between installations
- Backup calibrations for migration

Important:
- Bundles are DERIVED from database, never authoritative
- Production code never reads bundles directly

"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.components.ml.calibration_state_comp import (
    get_calibration_version,
    load_all_calibration_states,
)
from nomarr.helpers.time_helper import format_wall_timestamp, now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


def export_calibration_bundle_wf(
    db: Database,
    output_path: str,
    include_metadata: bool = True,
) -> dict[str, Any]:
    """Export calibration data from database to bundle JSON file.

    Reads all calibrations from calibration_state table and writes to
    JSON bundle file in standard format.

    BUNDLE FORMAT (output):
    {
        "labels": {
            "happy": {"p5": 0.123, "p95": 0.876, "method": "histogram"},
            "sad": {"p5": 0.100, "p95": 0.900, "method": "histogram"}
        },
        "metadata": {
            "generated_at": "2026-01-17T12:00:00Z",
            "version": "v1",
            "source": "nomarr-export",
            "global_version": "abc123..."
        }
    }

    Args:
        db: Database instance
        output_path: Path to write bundle JSON file
        include_metadata: If True, include metadata section

    Returns:
        Dict with export results:
            - exported_count: Number of calibrations exported
            - output_path: Path to written bundle file
            - global_version: Global calibration hash

    Raises:
        ValueError: If no calibrations exist in database

    """
    logger.info(f"[export_calibration] Exporting calibrations to {output_path}")

    # Read all calibrations from database
    calibration_states = load_all_calibration_states(db)

    if not calibration_states:
        msg = "No calibrations in database to export"
        raise ValueError(msg)

    # Build bundle structure
    labels: dict[str, dict[str, Any]] = {}

    for state in calibration_states:
        head_name = state.get("head_name")
        p5 = state.get("p5")
        p95 = state.get("p95")
        method = state.get("method", "histogram")

        if not head_name or p5 is None or p95 is None:
            logger.warning(f"[export_calibration] Skipping invalid state: {state}")
            continue

        # Extract label from head_name (e.g., "mood_happy" -> "happy")
        label = head_name.replace("mood_", "").replace("_", " ")

        labels[label] = {
            "p5": p5,
            "p95": p95,
            "method": method,
        }

    # Get global version
    global_version = get_calibration_version(db)

    # Build bundle
    bundle: dict[str, Any] = {"labels": labels}

    if include_metadata:
        bundle["metadata"] = {
            "generated_at": format_wall_timestamp(now_ms(), "%Y-%m-%dT%H:%M:%SZ"),
            "version": "v1",
            "source": "nomarr-export",
            "global_version": global_version,
            "calibration_count": len(labels),
        }

    # Write to file
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)

    logger.info(f"[export_calibration] Exported {len(labels)} calibrations to {output_path}")

    return {
        "exported_count": len(labels),
        "output_path": str(output),
        "global_version": global_version,
    }


def export_calibration_bundles_to_directory_wf(
    db: Database,
    models_dir: str,
    bundle_name: str = "calibration",
) -> dict[str, Any]:
    """Export calibrations as bundle files in models directory structure.

    Creates bundle files organized by model structure (e.g., effnet/heads/).

    Args:
        db: Database instance
        models_dir: Path to models directory
        bundle_name: Base name for bundle files (default: "calibration")

    Returns:
        Dict with export results:
            - bundles_created: Number of bundle files created
            - total_exported: Total calibrations exported
            - output_paths: List of created bundle paths

    """
    logger.info(f"[export_calibration] Exporting calibrations to {models_dir}")

    # For now, create single bundle file
    # TODO: Add logic to organize by model/backbone structure
    output_path = Path(models_dir) / f"{bundle_name}.json"

    try:
        result = export_calibration_bundle_wf(db, str(output_path))

        return {
            "bundles_created": 1,
            "total_exported": result["exported_count"],
            "output_paths": [result["output_path"]],
            "global_version": result["global_version"],
        }

    except Exception as e:
        logger.exception(f"[export_calibration] Export failed: {e}")
        return {
            "bundles_created": 0,
            "total_exported": 0,
            "output_paths": [],
            "global_version": None,
            "error": str(e),
        }
