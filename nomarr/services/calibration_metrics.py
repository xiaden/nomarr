"""
Calibration drift metrics calculation.

Provides functions to measure stability and drift between calibration runs.
Uses industry-standard metrics for distribution monitoring.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial.distance import jensenshannon
from scipy.stats import iqr


def calculate_apd(old_p5: float, old_p95: float, new_p5: float, new_p95: float) -> tuple[float, float]:
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


def calculate_srd(old_p5: float, old_p95: float, new_p5: float, new_p95: float) -> float:
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


def calculate_jsd(old_scores: np.ndarray, new_scores: np.ndarray, bins: int = 100) -> float:
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


def calculate_median_iqr_drift(old_scores: np.ndarray, new_scores: np.ndarray) -> tuple[float, float]:
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


def compare_calibrations(
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
    apd_p5, apd_p95 = calculate_apd(
        old_calibration["p5"], old_calibration["p95"], new_calibration["p5"], new_calibration["p95"]
    )
    srd = calculate_srd(old_calibration["p5"], old_calibration["p95"], new_calibration["p5"], new_calibration["p95"])
    jsd = calculate_jsd(old_scores, new_scores)
    median_drift, iqr_drift = calculate_median_iqr_drift(old_scores, new_scores)

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
