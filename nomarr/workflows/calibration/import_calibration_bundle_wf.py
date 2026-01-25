"""Import calibration bundles from disk into database.

ARCHITECTURE:
- Bundles are TRANSPORT ARTIFACTS for distribution (e.g., from nom-cal repo)
- Database (calibration_state) is the SINGLE SOURCE OF TRUTH
- This workflow parses bundle JSON → upserts to calibration_state → updates meta

USAGE:
- Pre-alpha: Download bundles from nom-cal repo for users without local generation
- Post-1.0: Allow importing calibrations from external sources

IMPORTANT:
- Production processing/recalibration NEVER reads bundles directly
- After import, all code uses calibration_loader_wf to read from DB
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


def import_calibration_bundle_wf(
    db: Database,
    bundle_path: str,
) -> dict[str, Any]:
    """Import calibration bundle from disk into database.

    Parses bundle JSON file, upserts calibrations to calibration_state,
    and updates global calibration version in meta collection.

    BUNDLE FORMAT (expected JSON structure):
    {
        "labels": {
            "happy": {"p5": 0.123, "p95": 0.876, "method": "histogram"},
            "sad": {"p5": 0.100, "p95": 0.900, "method": "histogram"}
        },
        "metadata": {
            "generated_at": "2026-01-17T12:00:00Z",
            "version": "v1",
            "source": "nom-cal"
        }
    }

    Args:
        db: Database instance
        bundle_path: Path to calibration bundle JSON file

    Returns:
        Dict with import results:
            - imported_count: Number of calibrations imported
            - skipped_count: Number skipped (invalid format)
            - errors: List of error messages
            - global_version: New global calibration hash

    Raises:
        FileNotFoundError: If bundle file doesn't exist
        ValueError: If bundle format invalid
    """
    logger.info(f"[import_calibration] Importing bundle from {bundle_path}")

    path = Path(bundle_path)
    if not path.exists():
        raise FileNotFoundError(f"Bundle file not found: {bundle_path}")

    # Parse bundle JSON
    try:
        with open(path, encoding="utf-8") as f:
            bundle_data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in bundle: {e}") from e

    # Extract calibrations
    labels = bundle_data.get("labels", {})
    if not labels:
        raise ValueError("Bundle contains no calibrations (missing 'labels' key)")

    # Import calibrations to database
    imported_count = 0
    skipped_count = 0
    errors: list[str] = []

    for label, params in labels.items():
        try:
            # Validate required fields
            p5 = params.get("p5")
            p95 = params.get("p95")

            if p5 is None or p95 is None:
                errors.append(f"Label '{label}': missing p5 or p95")
                skipped_count += 1
                continue

            # Upsert to calibration_state
            # Note: This assumes a head_name format (e.g., "mood_happy")
            # Adjust mapping as needed for your schema
            head_name = f"mood_{label.replace(' ', '_')}"
            model_key = params.get("model_key", "imported")  # Use model_key from bundle or default

            # Generate calibration_def_hash for tracking
            import hashlib

            calib_def = f"{model_key}:{head_name}:1"
            calibration_def_hash = hashlib.md5(calib_def.encode()).hexdigest()

            # Create histogram spec (default 10k bins)
            histogram_spec = {
                "lo": params.get("lo", 0.0),
                "hi": params.get("hi", 1.0),
                "bins": params.get("bins", 10000),
                "bin_width": (params.get("hi", 1.0) - params.get("lo", 0.0)) / params.get("bins", 10000),
            }

            db.calibration_state.upsert_calibration_state(
                model_key=model_key,
                head_name=head_name,
                calibration_def_hash=calibration_def_hash,
                version=params.get("version", 1),
                histogram_spec=histogram_spec,
                p5=float(p5),
                p95=float(p95),
                sample_count=params.get("n", 0),  # Unknown sample count for imported bundles
                underflow_count=params.get("underflow_count", 0),
                overflow_count=params.get("overflow_count", 0),
            )

            imported_count += 1
            logger.debug(f"[import_calibration] Imported {label}: p5={p5}, p95={p95}")

        except Exception as e:
            errors.append(f"Label '{label}': {e}")
            skipped_count += 1
            logger.error(f"[import_calibration] Failed to import {label}: {e}")

    # Update global calibration version
    from nomarr.components.ml.ml_calibration_comp import compute_global_calibration_hash

    calibration_states = db.calibration_state.get_all_calibration_states()
    global_version = compute_global_calibration_hash(calibration_states)
    db.meta.set("calibration_version", global_version)

    logger.info(
        f"[import_calibration] Import complete: {imported_count} imported, "
        f"{skipped_count} skipped, {len(errors)} errors"
    )

    return {
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "errors": errors,
        "global_version": global_version,
    }


def import_calibration_bundles_from_directory_wf(
    db: Database,
    models_dir: str,
    calibrate_heads: bool = False,
) -> dict[str, Any]:
    """Import all calibration bundles from models directory.

    Scans models directory for calibration bundle JSON files and imports them.

    BUNDLE SELECTION:
    - calibrate_heads=False (default): Import *-calibration.json (reference bundles)
    - calibrate_heads=True (dev mode): Import *-calibration-v*.json (versioned bundles)

    Args:
        db: Database instance
        models_dir: Path to models directory
        calibrate_heads: If True, import versioned bundles; if False, import reference bundles

    Returns:
        Dict with aggregated import results:
            - bundles_processed: Number of bundle files processed
            - total_imported: Total calibrations imported
            - total_skipped: Total calibrations skipped
            - global_version: Final global calibration hash
    """
    logger.info(f"[import_calibration] Scanning {models_dir} for calibration bundles")

    models_path = Path(models_dir)
    if not models_path.exists():
        logger.warning(f"[import_calibration] Models directory not found: {models_dir}")
        return {
            "bundles_processed": 0,
            "total_imported": 0,
            "total_skipped": 0,
            "global_version": None,
        }

    # Find bundle files
    if calibrate_heads:
        bundle_files = list(models_path.rglob("*-calibration-v*.json"))
        logger.debug(f"[import_calibration] Found {len(bundle_files)} versioned bundles (dev mode)")
    else:
        bundle_files = list(models_path.rglob("*-calibration.json"))
        # Filter out versioned files
        bundle_files = [f for f in bundle_files if "-calibration-v" not in f.name]
        logger.debug(f"[import_calibration] Found {len(bundle_files)} reference bundles")

    if not bundle_files:
        logger.warning("[import_calibration] No calibration bundles found")
        return {
            "bundles_processed": 0,
            "total_imported": 0,
            "total_skipped": 0,
            "global_version": None,
        }

    # Import each bundle
    total_imported = 0
    total_skipped = 0
    bundles_processed = 0

    for bundle_file in bundle_files:
        try:
            result = import_calibration_bundle_wf(db, str(bundle_file))
            total_imported += result["imported_count"]
            total_skipped += result["skipped_count"]
            bundles_processed += 1
        except Exception as e:
            logger.error(f"[import_calibration] Failed to import {bundle_file}: {e}")
            total_skipped += 1

    # Final global version (computed after all imports)
    from nomarr.components.ml.ml_calibration_comp import compute_global_calibration_hash

    calibration_states = db.calibration_state.get_all_calibration_states()
    global_version = compute_global_calibration_hash(calibration_states)

    logger.info(
        f"[import_calibration] Directory import complete: "
        f"{bundles_processed} bundles processed, {total_imported} calibrations imported"
    )

    return {
        "bundles_processed": bundles_processed,
        "total_imported": total_imported,
        "total_skipped": total_skipped,
        "global_version": global_version,
    }
