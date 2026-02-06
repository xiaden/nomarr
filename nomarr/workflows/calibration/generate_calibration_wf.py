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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.spatial.distance import jensenshannon
from scipy.stats import iqr

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
    progressive: bool = True,
    start_pct: float = 0.5,
    increment_pct: float = 0.05,
) -> dict[str, Any]:
    """Generate histogram-based calibrations for all model heads.

    Stateless, idempotent workflow. Always computes from current DB state.
    Uses sparse uniform histogram (10,000 bins) to derive p5/p95 percentiles.

    Progressive mode: Runs calibration multiple times with increasing sample sizes
    (50% → 55% → 60% → ... until 100%), storing convergence history.

    Args:
        db: Database instance
        models_dir: Path to models directory
        namespace: Tag namespace (default "nom")
        progressive: Enable progressive calibration with convergence tracking (default True)
        start_pct: Starting percentage of total files (default 0.5 = 50%)
        increment_pct: Percentage increment per iteration (default 0.05 = 5%)

    Returns:
        {
          "version": int,
          "heads_processed": int,
          "heads_success": int,
          "heads_failed": int,
          "results": {head_key: {p5, p95, n, underflow_count, overflow_count}},
          "progressive_iterations": int (if progressive=True),
          "convergence_history": [{iteration, sample_size, sample_pct, heads: {head_key: deltas}}] (if progressive=True)
        }

    """
    from nomarr.components.ml.ml_discovery_comp import discover_heads

    logger.info(
        f"[histogram_calibration_wf] Starting histogram-based calibration generation (progressive={progressive})",
    )

    # Discover all heads
    heads = discover_heads(models_dir)
    if not heads:
        logger.warning("[histogram_calibration_wf] No heads found in models directory")
        return {"version": 0, "heads_processed": 0, "heads_success": 0, "heads_failed": 0, "results": {}}

    logger.info(f"[histogram_calibration_wf] Discovered {len(heads)} heads")

    if not progressive:
        # Legacy mode: Single pass over all data
        return _run_single_calibration(db, models_dir, heads, namespace)

    # Progressive mode: Multiple iterations with increasing sample sizes
    return _run_progressive_calibration(
        db=db,
        models_dir=models_dir,
        heads=heads,
        namespace=namespace,
        start_sample_size=int(start_pct * 1000),  # Convert pct to initial sample size
        increment_size=int(increment_pct * 1000),
    )


def _run_single_calibration(db: Database, models_dir: str, heads: list[Any], namespace: str) -> dict[str, Any]:
    """Run calibration once over all available data (legacy mode)."""
    from nomarr.components.ml.ml_calibration_comp import generate_calibration_from_histogram

    results = {}
    success_count = 0
    failed_count = 0

    for head_info in heads:
        # Construct model_key from HeadInfo structure
        # Using simple format: backbone-release_date for model_key
        embedder_date = "unknown"
        if head_info.embedding_sidecar:
            embedder_release = head_info.embedding_sidecar.data.get("release_date", "")
            if embedder_release:
                embedder_date = embedder_release.replace("-", "")

        model_key = f"{head_info.backbone}-{embedder_date}"
        head_name = head_info.name  # Use head name from sidecar
        version = head_info.sidecar.data.get("version", 1)
        head_key = f"{model_key}:{head_name}"

        logger.info(f"[histogram_calibration_wf] Processing {head_key} (version {version})")

        try:
            # Generate calibration from histogram
            calib_result = generate_calibration_from_histogram(
                db=db, model_key=model_key, head_name=head_name, version=version, lo=0.0, hi=1.0, bins=10000,
            )

            # Compute calibration definition hash
            from nomarr.components.ml.ml_calibration_comp import compute_calibration_def_hash

            calib_def_hash = compute_calibration_def_hash(model_key, head_name, version)

            # Upsert calibration_state
            db.calibration_state.upsert_calibration_state(
                model_key=model_key,
                head_name=head_name,
                calibration_def_hash=calib_def_hash,
                version=version,
                histogram_spec={"lo": 0.0, "hi": 1.0, "bins": 10000, "bin_width": 0.0001},
                p5=calib_result["p5"],
                p95=calib_result["p95"],
                sample_count=calib_result["n"],
                underflow_count=calib_result["underflow_count"],
                overflow_count=calib_result["overflow_count"],
            )

            results[head_key] = calib_result
            success_count += 1

        except Exception as e:
            logger.exception(f"[histogram_calibration_wf] Failed to generate calibration for {head_key}: {e}")
            failed_count += 1

    logger.info(f"[histogram_calibration_wf] Completed: {success_count} success, {failed_count} failed")

    # Compute and store global calibration version
    from nomarr.components.ml.ml_calibration_comp import compute_global_calibration_hash

    all_calibration_states = db.calibration_state.get_all_calibration_states()
    global_version_hash = compute_global_calibration_hash(all_calibration_states)
    current_timestamp = str(int(__import__("time").time() * 1000))

    db.meta.set("calibration_version", global_version_hash)
    db.meta.set("calibration_last_run", current_timestamp)

    logger.info(f"[histogram_calibration_wf] Stored global calibration version: {global_version_hash[:12]}...")

    return {
        "version": 1,  # Placeholder - could derive from head metadata
        "heads_processed": len(heads),
        "heads_success": success_count,
        "heads_failed": failed_count,
        "results": results,
        "global_version": global_version_hash,
    }


def _run_progressive_calibration(
    db: Database, models_dir: str, heads: list[Any], namespace: str, start_sample_size: int, increment_size: int,
) -> dict[str, Any]:
    """Run calibration progressively: start with N files, add M more each iteration.
    Store convergence history in calibration_history collection.
    """
    from nomarr.components.ml.ml_calibration_comp import (
        compute_calibration_def_hash,
        compute_global_calibration_hash,
        generate_calibration_from_histogram_with_limit,
    )

    logger.info(f"[progressive_calibration] Starting: {start_sample_size} files → +{increment_size} per iteration")

    # Get total file count
    total_files = db.library_files.count_files_with_tags(namespace)
    if total_files == 0:
        logger.warning("[progressive_calibration] No tagged files found")
        return {
            "version": 0,
            "heads_processed": 0,
            "heads_success": 0,
            "heads_failed": 0,
            "results": {},
            "progressive_iterations": 0,
            "convergence_history": [],
        }

    logger.info(f"[progressive_calibration] Total tagged files: {total_files}")

    # Track previous iteration results for delta calculation
    previous_results: dict[str, dict[str, Any]] = {}
    convergence_history = []
    iteration = 0

    # Refuse to run progressive calibration without enough data
    if total_files < start_sample_size:
        msg = (
            f"Not enough tagged files for progressive calibration: "
            f"{total_files} files < {start_sample_size} required minimum"
        )
        logger.error(f"[progressive_calibration] {msg}")
        raise ValueError(msg)

    # Progressive loop: start_sample_size → +increment_size → until total_files
    current_sample_size = start_sample_size
    success_count = 0
    failed_count = 0
    while current_sample_size <= total_files:
        iteration += 1
        current_pct = current_sample_size / total_files
        logger.info(
            f"[progressive_calibration] Iteration {iteration}: {current_sample_size} files ({current_pct * 100:.0f}%)",
        )

        iteration_results = {}
        iteration_deltas = {}
        success_count = 0
        failed_count = 0

        for head_info in heads:
            # Construct identifiers
            embedder_date = "unknown"
            if head_info.embedding_sidecar:
                embedder_release = head_info.embedding_sidecar.data.get("release_date", "")
                if embedder_release:
                    embedder_date = embedder_release.replace("-", "")

            model_key = f"{head_info.backbone}-{embedder_date}"
            head_name = head_info.name
            version = head_info.sidecar.data.get("version", 1)
            head_key = f"{model_key}:{head_name}"

            try:
                # Generate calibration with sample limit
                calib_result = generate_calibration_from_histogram_with_limit(
                    db=db,
                    model_key=model_key,
                    head_name=head_name,
                    version=version,
                    lo=0.0,
                    hi=1.0,
                    bins=10000,
                    sample_limit=current_sample_size,
                )

                # Calculate deltas from previous iteration
                p5_delta = None
                p95_delta = None
                n_delta = None
                if head_key in previous_results:
                    prev = previous_results[head_key]
                    p5_delta = calib_result["p5"] - prev["p5"]
                    p95_delta = calib_result["p95"] - prev["p95"]
                    n_delta = calib_result["n"] - prev["n"]

                # Store snapshot in calibration_history
                calib_def_hash = compute_calibration_def_hash(model_key, head_name, version)
                calibration_key = f"{model_key}:{head_name}"

                db.calibration_history.create_snapshot(
                    calibration_key=calibration_key,
                    p5=calib_result["p5"],
                    p95=calib_result["p95"],
                    sample_count=calib_result["n"],
                    underflow_count=calib_result["underflow_count"],
                    overflow_count=calib_result["overflow_count"],
                    p5_delta=p5_delta,
                    p95_delta=p95_delta,
                    n_delta=n_delta,
                )

                # Update calibration_state with latest values
                db.calibration_state.upsert_calibration_state(
                    model_key=model_key,
                    head_name=head_name,
                    calibration_def_hash=calib_def_hash,
                    version=version,
                    histogram_spec={"lo": 0.0, "hi": 1.0, "bins": 10000, "bin_width": 0.0001},
                    p5=calib_result["p5"],
                    p95=calib_result["p95"],
                    sample_count=calib_result["n"],
                    underflow_count=calib_result["underflow_count"],
                    overflow_count=calib_result["overflow_count"],
                )

                iteration_results[head_key] = calib_result
                iteration_deltas[head_key] = {"p5_delta": p5_delta, "p95_delta": p95_delta, "n_delta": n_delta}
                success_count += 1

                logger.debug(
                    f"[progressive_calibration] {head_key}: p5={calib_result['p5']:.4f} "
                    f"(Δ{f'{p5_delta:.4f}' if p5_delta is not None else 'N/A'}), "
                    f"p95={calib_result['p95']:.4f} (Δ{f'{p95_delta:.4f}' if p95_delta is not None else 'N/A'})",
                )

            except Exception as e:
                logger.exception(f"[progressive_calibration] Failed {head_key}: {e}")
                failed_count += 1

        # Store iteration summary
        convergence_history.append(
            {
                "iteration": iteration,
                "sample_size": current_sample_size,
                "sample_pct": round(current_pct * 100, 1),
                "heads_success": success_count,
                "heads_failed": failed_count,
                "deltas": iteration_deltas,
            },
        )

        # Save results for next iteration's delta calculation
        previous_results = iteration_results

        # Increment sample size
        current_sample_size += increment_size

        # Stop if we've reached or exceeded total files
        if current_sample_size > total_files and iteration > 1:
            break

    logger.info(f"[progressive_calibration] Completed {iteration} iterations")

    # Update global calibration version
    all_calibration_states = db.calibration_state.get_all_calibration_states()
    global_version_hash = compute_global_calibration_hash(all_calibration_states)
    current_timestamp = str(int(__import__("time").time() * 1000))

    db.meta.set("calibration_version", global_version_hash)
    db.meta.set("calibration_last_run", current_timestamp)

    logger.info(f"[progressive_calibration] Global version: {global_version_hash[:12]}...")

    return {
        "version": 1,
        "heads_processed": len(heads),
        "heads_success": success_count,
        "heads_failed": failed_count,
        "results": previous_results,  # Final iteration results
        "global_version": global_version_hash,
        "progressive_iterations": iteration,
        "convergence_history": convergence_history,
    }
