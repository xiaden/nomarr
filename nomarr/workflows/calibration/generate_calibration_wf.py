"""Calibration generation workflow.

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

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.spatial.distance import jensenshannon
from scipy.stats import iqr

from nomarr.components.ml.calibration_state_comp import (
    load_all_calibration_states,
    save_calibration_state,
    set_calibration_last_run,
    set_calibration_version,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Workflow-Internal Helper DTOs
# ----------------------------------------------------------------------


@dataclass
class ParseTagKeyResult:
    """Result from _parse_tag_key() private helper (workflow-internal)."""

    model_name: str
    head_name: str
    label: str


@dataclass
class CompareCalibrationsResult:
    """Result from _compare_calibrations() private helper (workflow-internal)."""

    apd_p5: float
    apd_p95: float
    srd: float
    jsd: float
    median_drift: float
    iqr_drift: float
    is_stable: bool
    failed_metrics: list[str]


@dataclass
class CalculateHeadDriftResult:
    """Result from _calculate_head_drift() private helper (workflow-internal)."""

    apd_p5: float
    apd_p95: float
    srd: float
    jsd: float
    median_drift: float
    iqr_drift: float
    is_stable: bool
    failed_metrics: list[str]


# ----------------------------------------------------------------------
# Drift Metrics Functions (Internal to Calibration Workflow)
# ----------------------------------------------------------------------


def _calculate_apd(old_p5: float, old_p95: float, new_p5: float, new_p95: float) -> tuple[float, float]:
    """Calculate Absolute Percentile Drift (APD) for P5 and P95.

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
    """Calculate Scale Range Drift (SRD).

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
    """Calculate Jensen-Shannon Divergence (JSD) between score distributions.

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
    """Calculate median and IQR (Interquartile Range) drift.

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
    median_drift = float(abs(new_median - old_median))

    old_iqr = float(iqr(old_scores))
    new_iqr = float(iqr(new_scores))
    iqr_drift = abs(new_iqr - old_iqr)

    return median_drift, iqr_drift


def _compare_calibrations(
    old_calibration: dict,
    new_calibration: dict,
    old_scores: np.ndarray,
    new_scores: np.ndarray,
    thresholds: dict[str, float] | None = None,
) -> CompareCalibrationsResult:
    """Compare two calibration runs and calculate all drift metrics.

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
    default_thresholds = {"apd_p5": 0.01, "apd_p95": 0.01, "srd": 0.05, "jsd": 0.1, "median": 0.05, "iqr": 0.1}
    if thresholds:
        default_thresholds.update(thresholds)

    # Calculate all metrics
    apd_p5, apd_p95 = _calculate_apd(
        old_calibration["p5"], old_calibration["p95"], new_calibration["p5"], new_calibration["p95"],
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

    return CompareCalibrationsResult(
        apd_p5=apd_p5,
        apd_p95=apd_p95,
        srd=srd,
        jsd=jsd,
        median_drift=median_drift,
        iqr_drift=iqr_drift,
        is_stable=is_stable,
        failed_metrics=failed_metrics,
    )


# =============================================================================
# Histogram-Based Calibration Workflow
# =============================================================================


def generate_histogram_calibration_wf(
    db: Database,
    models_dir: str,
    namespace: str = "nom",
    progress_callback: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Generate histogram-based calibrations for all model labels (single pass).

    Per-label semantics: Iterates over heads, then for each head iterates over
    its labels, generating independent calibrations. Binary classification heads
    (e.g., gender) produce 2 calibration documents (male, female), each with
    independent P5/P95 ranges. Regression heads produce 1 calibration per label.
    Total: 22 calibration_state documents across 12 heads.

    Stateless, idempotent workflow. Always computes from current DB state.
    Uses sparse uniform histogram (10,000 bins) to derive p5/p95 percentiles.

    Args:
        db: Database instance
        models_dir: Path to models directory
        namespace: Tag namespace (default "nom")
        progress_callback: Optional callback for progress updates (per-head granularity)

    Returns:
        {
          "version": int,
          "heads_processed": int,
          "heads_success": int,
          "heads_failed": int,
          "results": {label_key: {p5, p95, n, underflow_count, overflow_count}},
          "global_version": str
        }

    Note:
        results keys are "model:head:label" format (e.g., "effnet-20220825:gender:male").

    """
    from nomarr.components.ml.ml_calibration_comp import (
        compute_calibration_def_hash,
        compute_global_calibration_hash,
        generate_calibration_from_histogram,
    )
    from nomarr.components.ml.ml_discovery_comp import discover_heads
    from nomarr.components.tagging.tagging_aggregation_comp import normalize_tag_label

    logger.info("[histogram_calibration_wf] Starting histogram-based calibration generation")

    # Discover all heads
    heads = discover_heads(models_dir)
    if not heads:
        logger.warning("[histogram_calibration_wf] No heads found in models directory")
        return {"version": 0, "heads_processed": 0, "heads_success": 0, "heads_failed": 0, "results": {}}

    logger.info(f"[histogram_calibration_wf] Discovered {len(heads)} heads")

    results = {}
    success_count = 0
    failed_count = 0
    total_heads = len(heads)

    for head_idx, head_info in enumerate(heads):
        # Construct identifiers
        embedder_date = "unknown"
        if head_info.embedding_sidecar:
            embedder_release = head_info.embedding_sidecar.data.get("release_date", "")
            if embedder_release:
                embedder_date = embedder_release.replace("-", "")

        model_key = f"{head_info.backbone}-{embedder_date}"
        head_name = head_info.name
        labels = head_info.labels
        version = head_info.sidecar.data.get("version", 1)

        logger.info(f"[histogram_calibration_wf] Processing head {head_name} (version {version}, labels={labels})")

        # Report progress (per-head, outer loop)
        if progress_callback:
            progress_callback(
                current_head=head_name,
                current_head_index=head_idx + 1,
                total_heads=total_heads,
            )

        # Iterate over labels (per-label calibration)
        for raw_label in labels:
            # Normalize label to match DB tag format ("non_party" → "not_party")
            label = normalize_tag_label(raw_label)
            label_key = f"{model_key}:{head_name}:{label}"
            logger.info(f"[histogram_calibration_wf] Processing label {label_key}")

            try:
                # Generate calibration from histogram (single label)
                calib_result = generate_calibration_from_histogram(
                    db=db,
                    model_key=model_key,
                    head_name=head_name,
                    label=label,
                    version=version,
                    lo=0.0,
                    hi=1.0,
                    bins=10000,
                )

                # Compute calibration definition hash (includes label)
                calib_def_hash = compute_calibration_def_hash(model_key, head_name, label, version)

                # Upsert calibration_state (includes label)
                save_calibration_state(
                    db,
                    model_key=model_key,
                    head_name=head_name,
                    label=label,
                    calibration_def_hash=calib_def_hash,
                    version=version,
                    histogram_spec={"lo": 0.0, "hi": 1.0, "bins": 10000, "bin_width": 0.0001},
                    p5=calib_result["p5"],
                    p95=calib_result["p95"],
                    sample_count=calib_result["n"],
                    underflow_count=calib_result["underflow_count"],
                    overflow_count=calib_result["overflow_count"],
                    histogram_bins=calib_result.get("histogram_bins"),
                )

                results[label_key] = calib_result
                success_count += 1

                logger.debug(
                    f"[histogram_calibration_wf] {label_key}: p5={calib_result['p5']:.4f}, "
                    f"p95={calib_result['p95']:.4f}, n={calib_result['n']}",
                )

            except Exception as e:
                logger.exception(f"[histogram_calibration_wf] Failed to generate calibration for {label_key}: {e}")
                failed_count += 1

    logger.info(f"[histogram_calibration_wf] Completed: {success_count} success, {failed_count} failed")

    # Compute and store global calibration version
    all_calibration_states = load_all_calibration_states(db)
    global_version_hash = compute_global_calibration_hash(all_calibration_states)
    current_timestamp = str(int(__import__("time").time() * 1000))

    set_calibration_version(db, global_version_hash)
    set_calibration_last_run(db, current_timestamp)

    logger.info(f"[histogram_calibration_wf] Stored global calibration version: {global_version_hash[:12]}...")

    return {
        "version": 1,
        "heads_processed": len(heads),
        "heads_success": success_count,
        "heads_failed": failed_count,
        "results": results,
        "global_version": global_version_hash,
    }


