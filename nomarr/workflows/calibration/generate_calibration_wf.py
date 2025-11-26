"""
Calibration generation workflow.

This workflow generates calibrations for all model heads with drift tracking:
- Queries library tags to compute min/max calibrations
- Calculates drift metrics by comparing to reference calibrations
- Stores calibration history in database
- Saves versioned calibration sidecar files
- Updates reference calibration files for unstable heads

ARCHITECTURE:
- This is a PURE WORKFLOW that orchestrates: ML calibration, DB tracking, file I/O
- It does NOT import services, interfaces, or the application object
- Callers must provide all dependencies: db, models_dir, namespace, thresholds

EXPECTED DEPENDENCIES:
- `db: Database` - Database instance with calibration and library accessors
- `models_dir: str` - Path to models directory (for saving/loading calibrations)
- `namespace: str` - Tag namespace (e.g., "nom")
- `thresholds: dict[str, float] | None` - Custom drift thresholds

USAGE:
    from nomarr.workflows.calibration.generate_calibration_wf import generate_calibration_workflow

    result = generate_calibration_workflow(
        db=database_instance,
        models_dir="/app/models",
        namespace="nom",
        thresholds={"apd_p5": 0.01, "srd": 0.05, ...}
    )
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.spatial.distance import jensenshannon
from scipy.stats import iqr

from nomarr.components.ml.ml_calibration_comp import generate_minmax_calibration, save_calibration_sidecars

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Drift Metrics Functions (Internal to Calibration Workflow)
# ----------------------------------------------------------------------


def _calculate_apd(old_p5: float, old_p95: float, new_p5: float, new_p95: float) -> tuple[float, float]:
    """
    Calculate Absolute Percentile Drift (APD) for P5 and P95.

    APD measures how much the extreme percentiles have shifted between calibrations.
    Lower values indicate stability.

    Thresholds (recommended):
    - <0.01: Very stable
    - 0.01-0.03: Acceptable
    - 0.05+: Unstable
    - 0.10+: Recalibration needed

    Args:
        old_p5: Previous 5th percentile
        old_p95: Previous 95th percentile
        new_p5: Current 5th percentile
        new_p95: Current 95th percentile

    Returns:
        Tuple of (apd_p5, apd_p95)
    """
    apd_p5 = abs(new_p5 - old_p5)
    apd_p95 = abs(new_p95 - old_p95)
    return apd_p5, apd_p95


def _calculate_srd(old_p5: float, old_p95: float, new_p5: float, new_p95: float) -> float:
    """
    Calculate Scale Range Drift (SRD).

    SRD measures how much the calibrated dynamic range has changed.
    Indicates if the scale mapping is stable.

    Thresholds (recommended):
    - <0.05: Excellent (5%)
    - 0.05-0.10: Normal (5-10%)
    - 0.15+: Unstable (15%)

    Args:
        old_p5: Previous 5th percentile
        old_p95: Previous 95th percentile
        new_p5: Current 5th percentile
        new_p95: Current 95th percentile

    Returns:
        Scale range drift (absolute change in range)
    """
    old_range = old_p95 - old_p5
    new_range = new_p95 - new_p5
    return abs(new_range - old_range)


def _calculate_jsd(old_scores: np.ndarray, new_scores: np.ndarray, bins: int = 100) -> float:
    """
    Calculate Jensen-Shannon Divergence (JSD) between score distributions.

    JSD measures the similarity of distribution shapes. It's symmetric and
    bounded [0, 1], making it ideal for comparing calibration runs.

    Thresholds (recommended):
    - 0.0: Identical distributions
    - <0.1: Similar distributions
    - 0.1-0.2: Distribution shift
    - 0.3+: Major problem

    Args:
        old_scores: Previous raw model scores (1D array)
        new_scores: Current raw model scores (1D array)
        bins: Number of histogram bins (default 100)

    Returns:
        Jensen-Shannon divergence [0, 1]
    """
    # Create histograms with same bin edges
    bin_edges = np.linspace(0, 1, bins + 1)
    old_hist, _ = np.histogram(old_scores, bins=bin_edges, density=True)
    new_hist, _ = np.histogram(new_scores, bins=bin_edges, density=True)

    # Normalize to probability distributions
    old_hist = old_hist / old_hist.sum()
    new_hist = new_hist / new_hist.sum()

    # Calculate JSD (returns sqrt of JS divergence, need to square it)
    jsd_distance = jensenshannon(old_hist, new_hist)
    return float(jsd_distance**2)  # Square to get actual JS divergence


def _calculate_median_iqr_drift(old_scores: np.ndarray, new_scores: np.ndarray) -> tuple[float, float]:
    """
    Calculate median and IQR (Interquartile Range) drift.

    These provide center shift and spread shift measurements that are
    robust to outliers (unlike mean/std).

    Thresholds (recommended):
    - Median drift <0.05: Stable center
    - IQR drift <0.10: Stable spread

    Args:
        old_scores: Previous raw model scores (1D array)
        new_scores: Current raw model scores (1D array)

    Returns:
        Tuple of (median_drift, iqr_drift)
    """
    old_median = np.median(old_scores)
    new_median = np.median(new_scores)
    median_drift = abs(new_median - old_median)

    old_iqr = iqr(old_scores)
    new_iqr = iqr(new_scores)
    iqr_drift = abs(new_iqr - old_iqr)

    return float(median_drift), float(iqr_drift)


def _compare_calibrations(
    old_calibration: dict,
    new_calibration: dict,
    old_scores: np.ndarray,
    new_scores: np.ndarray,
    thresholds: dict[str, float] | None = None,
) -> dict:
    """
    Compare two calibration runs and calculate all drift metrics.

    Args:
        old_calibration: Previous calibration dict with 'p5' and 'p95' keys
        new_calibration: Current calibration dict with 'p5' and 'p95' keys
        old_scores: Previous raw model scores (1D array)
        new_scores: Current raw model scores (1D array)
        thresholds: Optional custom thresholds dict with keys:
            - apd_p5, apd_p95, srd, jsd, median, iqr

    Returns:
        Dict containing:
            - apd_p5: Absolute percentile drift for P5
            - apd_p95: Absolute percentile drift for P95
            - srd: Scale range drift
            - jsd: Jensen-Shannon divergence
            - median_drift: Median shift
            - iqr_drift: IQR shift
            - is_stable: Boolean (True if all metrics under threshold)
            - failed_metrics: List of metric names that exceeded threshold
    """
    # Default thresholds (conservative)
    default_thresholds = {
        "apd_p5": 0.01,
        "apd_p95": 0.01,
        "srd": 0.05,
        "jsd": 0.1,
        "median": 0.05,
        "iqr": 0.1,
    }
    if thresholds:
        default_thresholds.update(thresholds)

    # Calculate all metrics
    apd_p5, apd_p95 = _calculate_apd(
        old_calibration["p5"], old_calibration["p95"], new_calibration["p5"], new_calibration["p95"]
    )
    srd = _calculate_srd(old_calibration["p5"], old_calibration["p95"], new_calibration["p5"], new_calibration["p95"])
    jsd = _calculate_jsd(old_scores, new_scores)
    median_drift, iqr_drift = _calculate_median_iqr_drift(old_scores, new_scores)

    # Check stability (all metrics must be under threshold)
    failed_metrics = []
    if apd_p5 > default_thresholds["apd_p5"]:
        failed_metrics.append("apd_p5")
    if apd_p95 > default_thresholds["apd_p95"]:
        failed_metrics.append("apd_p95")
    if srd > default_thresholds["srd"]:
        failed_metrics.append("srd")
    if jsd > default_thresholds["jsd"]:
        failed_metrics.append("jsd")
    if median_drift > default_thresholds["median"]:
        failed_metrics.append("median_drift")
    if iqr_drift > default_thresholds["iqr"]:
        failed_metrics.append("iqr_drift")

    is_stable = len(failed_metrics) == 0

    return {
        "apd_p5": apd_p5,
        "apd_p95": apd_p95,
        "srd": srd,
        "jsd": jsd,
        "median_drift": median_drift,
        "iqr_drift": iqr_drift,
        "is_stable": is_stable,
        "failed_metrics": failed_metrics,
    }


def generate_calibration_workflow(
    db: Database,
    models_dir: str,
    namespace: str,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Generate calibrations for all heads and track drift metrics.

    This workflow orchestrates the complete calibration generation pipeline:
    1. Generates calibration from library tags (min/max per label)
    2. Determines next version number (max version + 1 across all heads)
    3. For each head: compares to reference, calculates drift, stores metadata
    4. Saves versioned calibration files to models directory
    5. Updates reference calibration files for unstable heads

    Args:
        db: Database instance (must provide calibration and library accessors)
        models_dir: Path to models directory for saving/loading calibrations
        namespace: Tag namespace (must be provided by service)
        thresholds: Optional custom drift thresholds for stability detection
                   (e.g., {"apd_p5": 0.01, "apd_p95": 0.01, "srd": 0.05, ...})

    Returns:
        Dict with calibration results:
        - version: int | None - New calibration version number
        - library_size: int - Number of files analyzed
        - heads: dict - Per-head results with drift metrics
        - saved_files: dict - Paths to saved calibration files
        - reference_updates: dict - Reference file update actions
        - summary: dict - Overall statistics (total_heads, stable_heads, unstable_heads)

    Example:
        >>> result = generate_calibration_workflow(
        ...     db=my_db, models_dir="/app/models", namespace="nom", thresholds={"apd_p5": 0.01}
        ... )
        >>> print(f"Generated calibration v{result['version']}")
    """
    logger.info("[calibration_workflow] Generating calibration with drift tracking")

    thresholds = thresholds or {}

    # Generate calibration data from library
    calibration_data = generate_minmax_calibration(db=db, namespace=namespace)

    library_size = calibration_data.get("library_size", 0)
    calibrations = calibration_data.get("calibrations", {})

    if not calibrations:
        logger.warning("[calibration_workflow] No calibrations generated (empty library or insufficient samples)")
        return {
            "version": None,
            "library_size": library_size,
            "heads": {},
            "saved_files": {},
            "summary": {"total_heads": 0, "stable_heads": 0, "unstable_heads": 0},
        }

    # Determine next version number (global across all heads for this run)
    next_version = _get_next_version(db)

    logger.info(f"[calibration_workflow] Generating calibration version {next_version} from {library_size} files")

    # Parse calibrations by head and track drift
    head_results: dict[str, Any] = {}

    for tag_key, calib_stats in calibrations.items():
        # Parse tag key to extract model_name and head_name
        parsed = _parse_tag_key(tag_key)
        if not parsed:
            logger.warning(f"[calibration_workflow] Cannot parse tag key: {tag_key}")
            continue

        model_name, head_name, label = parsed

        # Create unique key for this head
        head_key = f"{model_name}/{head_name}"

        # Track this head's calibration (one entry per head, aggregate all labels)
        if head_key not in head_results:
            head_results[head_key] = {
                "model_name": model_name,
                "head_name": head_name,
                "labels": {},
                "drift_metrics": None,
                "is_stable": None,
                "reference_version": None,
            }

        # Store label calibration data
        head_results[head_key]["labels"][label] = calib_stats

    # For each head, calculate drift and store in DB
    for head_key, head_data in head_results.items():
        model_name = head_data["model_name"]
        head_name = head_data["head_name"]
        labels = head_data["labels"]

        # Get reference calibration (most recent stable version)
        reference = db.calibration_runs.get_reference_calibration_run(model_name, head_name)

        # Calculate drift if reference exists
        drift_result = None
        if reference:
            drift_result = _calculate_head_drift(
                labels=labels,
                reference_run=reference,
                model_name=model_name,
                head_name=head_name,
                models_dir=models_dir,
                thresholds=thresholds,
            )
            head_data["drift_metrics"] = drift_result
            head_data["is_stable"] = drift_result["is_stable"]
            head_data["reference_version"] = reference["version"]
        else:
            # First calibration - always stable (no comparison)
            head_data["is_stable"] = True
            head_data["reference_version"] = None
            logger.info(f"[calibration_workflow] {head_key}: First calibration (v{next_version})")

        # Calculate aggregate p5/p95/range across all labels for this head
        all_p5 = [calib["p5"] for calib in labels.values()]
        all_p95 = [calib["p95"] for calib in labels.values()]
        avg_p5 = float(np.mean(all_p5))
        avg_p95 = float(np.mean(all_p95))
        avg_range = avg_p95 - avg_p5

        # Store calibration run in database
        db.calibration_runs.insert_calibration_run(
            model_name=model_name,
            head_name=head_name,
            version=next_version,
            file_count=library_size,
            p5=avg_p5,
            p95=avg_p95,
            range_val=avg_range,
            reference_version=head_data["reference_version"],
            apd_p5=drift_result["apd_p5"] if drift_result else None,
            apd_p95=drift_result["apd_p95"] if drift_result else None,
            srd=drift_result["srd"] if drift_result else None,
            jsd=drift_result["jsd"] if drift_result else None,
            median_drift=drift_result["median_drift"] if drift_result else None,
            iqr_drift=drift_result["iqr_drift"] if drift_result else None,
            is_stable=head_data["is_stable"],
        )

        # Log result
        if drift_result:
            stability_str = "STABLE" if drift_result["is_stable"] else "UNSTABLE"
            failed_metrics = drift_result.get("failed_metrics", [])
            logger.info(
                f"[calibration_workflow] {head_key} v{next_version}: {stability_str} "
                f"(ref=v{head_data['reference_version']}, "
                f"failed={failed_metrics if failed_metrics else 'none'})"
            )

    # Save calibration sidecars (versioned files)
    saved_files = save_calibration_sidecars(
        calibration_data=calibration_data, models_dir=models_dir, version=next_version
    )

    # Update reference calibration files for unstable heads
    reference_updates = _update_reference_files(head_results, next_version, models_dir)

    # Generate summary
    stable_count: int = sum(1 for h in head_results.values() if h["is_stable"])
    unstable_count = len(head_results) - stable_count

    summary = {
        "version": next_version,
        "library_size": library_size,
        "heads": head_results,
        "saved_files": saved_files,
        "reference_updates": reference_updates,
        "summary": {
            "total_heads": len(head_results),
            "stable_heads": stable_count,
            "unstable_heads": unstable_count,
        },
    }

    logger.info(
        f"[calibration_workflow] Calibration v{next_version} complete: "
        f"{stable_count} stable, {unstable_count} unstable (total {len(head_results)} heads)"
    )

    return summary


# ----------------------------------------------------------------------
# Private Helper Functions
# ----------------------------------------------------------------------


def _get_next_version(db: Database) -> int:
    """
    Get next calibration version number.

    Version is global across all heads for a given run.
    Finds the maximum version across all heads and adds 1.

    Args:
        db: Database instance

    Returns:
        Next version number (starts at 1)
    """
    all_runs = db.calibration_runs.list_calibration_runs(limit=10000)

    if not all_runs:
        return 1

    max_version: int = max(run["version"] for run in all_runs)
    return max_version + 1


def _parse_tag_key(tag_key: str) -> tuple[str, str, str] | None:
    """
    Parse tag key to extract model_name, head_name, and label.

    Tag format: label_framework_embedder{date}_label{date}_calib_version
    Example: happy_essentia21b6dev1389_yamnet20210604_happy20220825_none_0

    Args:
        tag_key: Tag key string to parse

    Returns:
        Tuple of (model_name, head_name, label) or None if parse fails
    """
    parts = tag_key.split("_")
    if len(parts) < 5:
        return None

    # Extract embedder (backbone) - at index -4
    embedder_part = parts[-4]  # e.g., "yamnet20210604"

    # Extract head part - at index -3
    head_part = parts[-3]  # e.g., "happy20220825"

    # Extract label from head part (everything before the 8-digit date)
    if len(head_part) < 8 or not head_part[-8:].isdigit():
        return None
    head_name = head_part[:-8] if len(head_part) > 8 else parts[0]

    # Extract backbone from embedder part
    model_name = None
    for i in range(len(embedder_part) - 7):
        if embedder_part[i : i + 2] == "20" and embedder_part[i : i + 8].isdigit():
            model_name = embedder_part[:i]
            break

    if not model_name:
        return None

    # Label is the first part of the tag key
    label = parts[0]

    return (model_name, head_name, label)


def _calculate_head_drift(
    labels: dict[str, dict],
    reference_run: dict,
    model_name: str,
    head_name: str,
    models_dir: str,
    thresholds: dict[str, float],
) -> dict:
    """
    Calculate drift metrics for a head by comparing to reference calibration.

    Args:
        labels: Dict of label -> calibration stats for new run
        reference_run: Reference calibration run from DB
        model_name: Model identifier
        head_name: Head identifier
        models_dir: Path to models directory
        thresholds: Drift thresholds for stability detection

    Returns:
        Drift metrics dict with stability status
    """
    # Load reference calibration file to get old scores
    reference_version = reference_run["version"]
    reference_file = _find_calibration_file(models_dir, model_name, head_name, reference_version)

    if not reference_file or not os.path.exists(reference_file):
        logger.warning(
            f"[calibration_workflow] Reference calibration file not found: {reference_file}. Treating as first run."
        )
        # No reference file - treat as first calibration
        return {
            "apd_p5": 0.0,
            "apd_p95": 0.0,
            "srd": 0.0,
            "jsd": 0.0,
            "median_drift": 0.0,
            "iqr_drift": 0.0,
            "is_stable": True,
            "failed_metrics": [],
        }

    # Load old calibration data
    with open(reference_file, encoding="utf-8") as f:
        old_calib_data = json.load(f)

    old_labels = old_calib_data.get("labels", {})

    # Aggregate p5/p95 across all labels
    old_p5_values = [calib["p5"] for calib in old_labels.values()]
    old_p95_values = [calib["p95"] for calib in old_labels.values()]
    new_p5_values = [calib["p5"] for calib in labels.values()]
    new_p95_values = [calib["p95"] for calib in labels.values()]

    # Create synthetic "old" and "new" calibration dicts for comparison
    old_calibration = {"p5": float(np.mean(old_p5_values)), "p95": float(np.mean(old_p95_values))}
    new_calibration = {"p5": float(np.mean(new_p5_values)), "p95": float(np.mean(new_p95_values))}

    # For JSD calculation, we need score distributions
    old_scores = _synthesize_distribution(old_labels)
    new_scores = _synthesize_distribution(labels)

    # Calculate drift metrics
    drift_result = _compare_calibrations(
        old_calibration=old_calibration,
        new_calibration=new_calibration,
        old_scores=old_scores,
        new_scores=new_scores,
        thresholds=thresholds,
    )

    return drift_result


def _find_calibration_file(models_dir: str, model_name: str, head_name: str, version: int) -> str | None:
    """
    Find calibration file path for a specific model/head/version.

    Args:
        models_dir: Path to models directory
        model_name: Model identifier (e.g., "effnet")
        head_name: Head identifier (e.g., "mood_happy")
        version: Calibration version number

    Returns:
        Path to calibration file or None if not found
    """
    # Search for calibration file in models directory
    # Format: models/{backbone}/heads/{head_name}-calibration-v{version}.json
    search_path = os.path.join(models_dir, model_name, "heads")
    if not os.path.exists(search_path):
        return None

    # Find matching calibration file
    for filename in os.listdir(search_path):
        if filename.startswith(head_name) and filename.endswith(f"-calibration-v{version}.json"):
            return os.path.join(search_path, filename)

    return None


def _synthesize_distribution(labels: dict[str, dict]) -> np.ndarray:
    """
    Synthesize score distribution from label calibration stats.

    Uses mean/std to generate approximate distribution for JSD calculation.
    This is an approximation - ideally we'd store raw scores in DB.

    Args:
        labels: Dict of label -> calibration stats

    Returns:
        Numpy array of synthesized scores
    """
    all_scores = []
    for calib in labels.values():
        mean = calib.get("mean", 0.5)
        std = calib.get("std", 0.1)
        samples = calib.get("samples", 1000)

        # Generate normal distribution centered at mean with given std
        scores = np.random.normal(mean, std, min(samples, 1000))
        # Clamp to [0, 1]
        scores = np.clip(scores, 0.0, 1.0)
        all_scores.extend(scores)

    return np.array(all_scores)


def _update_reference_files(head_results: dict, version: int, models_dir: str) -> dict[str, str]:
    """
    Update reference calibration files for unstable heads.

    When a head becomes unstable, its new calibration version becomes the reference.
    This copies the versioned file to calibration.json (the default file used by inference).

    Args:
        head_results: Dict of head results with stability info
        version: New calibration version number
        models_dir: Path to models directory

    Returns:
        Dict of head_key -> action taken ("updated", "unchanged", "error")
    """
    updates = {}

    for head_key, head_data in head_results.items():
        model_name = head_data["model_name"]
        head_name = head_data["head_name"]
        is_stable = head_data["is_stable"]

        # Find versioned calibration file for this head
        versioned_file = _find_calibration_file(models_dir, model_name, head_name, version)

        if not versioned_file or not os.path.exists(versioned_file):
            logger.warning(f"[calibration_workflow] Versioned file not found for {head_key} v{version}")
            updates[head_key] = "error"
            continue

        # Determine reference file path (same directory, but "calibration.json" name)
        ref_file = versioned_file.replace(f"-calibration-v{version}.json", "-calibration.json")

        # Update reference file if head is unstable OR if no reference exists yet
        should_update = not is_stable or not os.path.exists(ref_file)

        if should_update:
            try:
                shutil.copy2(versioned_file, ref_file)
                logger.info(
                    f"[calibration_workflow] Updated reference calibration: {head_key} -> v{version} "
                    f"({'first' if not os.path.exists(ref_file) else 'unstable'})"
                )
                updates[head_key] = "updated"
            except Exception as e:
                logger.error(f"[calibration_workflow] Failed to update reference for {head_key}: {e}")
                updates[head_key] = "error"
        else:
            # Stable - keep existing reference
            logger.debug(f"[calibration_workflow] {head_key} stable, keeping existing reference")
            updates[head_key] = "unchanged"

    return updates
