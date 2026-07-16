#!/usr/bin/env python3
"""
Head calibration + STD gate audit.

For every (head, label) pair this script reports:
  - Raw mean/std distribution (p25/p50/p75/p90/p95/max)
  - Calibration p5, p95, and the resulting scale factor 1/(p95-p5)
  - Gate simulation: fraction of files that would be fully gated out vs capped
    at low/medium vs allowed through to high — using the *current* thresholds
    (acceptable=0.25, stable=0.15, very_stable=0.08)
  - Current tier hit counts (strict / regular / loose) pulled from the tag graph
  - Distribution shape (bimodal / compressed / skewed / bell) inferred from means
  - Calibration method recommendation per shape

NOTE: This script previously connected to ArangoDB directly.  It needs to be
ported to use the PostgreSQL persistence layer (db.calibration, db.tags).

Usage:
    .venv/Scripts/python.exe scripts/diagnostics/head_calibration_audit.py
"""

from __future__ import annotations

import argparse
import datetime
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats as spstats

# ── defaults ────────────────────────────────────────────────────────────────

DEFAULT_DB = "nomarr"

# Stability thresholds — must match tagging_aggregation_comp.py DEFAULT_STABILITY_THRESHOLDS
GATE_ACCEPTABLE = 0.25
GATE_STABLE = 0.15
GATE_VERY_STABLE = 0.08

# ── CLI ─────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    return p.parse_args()


# ── DB helpers ───────────────────────────────────────────────────────────────

# NOTE: DB queries previously used ArangoDB AQL via python-arango.
# This script needs to be ported to use the PostgreSQL persistence layer
# (db.calibration, db.tags, db.segment_scores_stats).


# ── distribution shape ───────────────────────────────────────────────────────


def classify_distribution(means: np.ndarray) -> tuple[str, str]:
    """
    Returns (shape_label, calibration_recommendation).

    Shapes:
      compressed   IQR < 0.05 — whole library jammed near one value
      bimodal      substantial mass in both tails (< 0.35 and > 0.65)
      skewed-high  median > 0.60
      skewed-low   median < 0.40
      bell         roughly symmetric, IQR normal-ish
    """
    if len(means) < 10:
        return "insufficient", "n/a"

    q25, q50, q75 = np.percentile(means, [25, 50, 75])
    iqr = q75 - q25
    pct_low = np.mean(means < 0.35)
    pct_high = np.mean(means > 0.65)

    # Bimodality coefficient (>0.555 suggests bimodal)
    sk = float(spstats.skew(means))
    ku = float(spstats.kurtosis(means))  # excess kurtosis
    n = len(means)
    bc = (sk**2 + 1) / (ku + 3 * (n - 1) ** 2 / ((n - 2) * (n - 3)))

    if iqr < 0.05:
        return "compressed", "→ gate raw std (threshold *= cal_span); scale is the bug"
    if pct_low > 0.15 and pct_high > 0.15:
        return "bimodal", "→ minmax OK; gate thresholds need raising (bimodal std is naturally high)"
    if bc > 0.555 and pct_low > 0.15 and pct_high > 0.15:
        return "bimodal", "→ minmax OK; gate thresholds need raising"
    if q50 > 0.60:
        return "skewed-high", "→ minmax OK; consider raising gate thresholds"
    if q50 < 0.40:
        return "skewed-low", "→ minmax OK; consider raising gate thresholds"
    return "bell", "→ minmax OK"


# ── gate simulation ──────────────────────────────────────────────────────────

# Threshold sweep: for bimodal 1x heads (exponent stays at 1.0)
SWEEP_THRESHOLDS = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50]

# Exponent sweep: for compressed high-scale heads
# Range is (0.5, 1.0] — closer to 1 preserves more gating
SWEEP_EXPONENTS = [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 1.00]


def _none_pct(ss: np.ndarray, threshold: float) -> float:
    return float(np.mean(ss >= threshold)) if len(ss) else 1.0


def simulate_gates(raw_stds: np.ndarray, scale: float, exponent: float = 1.0) -> dict[str, float]:
    """
    Returns fraction of files in each gate bucket.
      exponent < 1.0 dampens scale explosion on compressed-distribution heads.
      exponent=1.0 is current behaviour (full linear scale).
    """
    ss = raw_stds * (scale**exponent)
    n = len(ss)
    if n == 0:
        return {"full": 0.0, "med": 0.0, "low": 0.0, "none": 0.0}
    return {
        "full": float(np.mean(ss < GATE_VERY_STABLE)),
        "med": float(np.mean((ss >= GATE_VERY_STABLE) & (ss < GATE_STABLE))),
        "low": float(np.mean((ss >= GATE_STABLE) & (ss < GATE_ACCEPTABLE))),
        "none": float(np.mean(ss >= GATE_ACCEPTABLE)),
    }


def threshold_sweep(raw_stds: np.ndarray, scale: float) -> dict[float, float]:
    """none% at each threshold in SWEEP_THRESHOLDS at exponent=1.0 (bimodal heads)."""
    ss = raw_stds * scale
    return {t: _none_pct(ss, t) for t in SWEEP_THRESHOLDS}


def exponent_sweep(raw_stds: np.ndarray, scale: float) -> dict[float, float]:
    """none% at acceptable=0.25 for each exponent in SWEEP_EXPONENTS (compressed heads)."""
    return {e: _none_pct(raw_stds * (scale**e), GATE_ACCEPTABLE) for e in SWEEP_EXPONENTS}


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    args = parse_args()

    print("Head Calibration Audit — PostgreSQL porting required.")
    print("This script previously connected to ArangoDB directly.")
    print("Port to use the PostgreSQL persistence layer:")
    print("  - db.calibration for calibration_state records")
    print("  - db.tags for tier hit counts")
    print("  - db.segment_scores_stats for segment score distributions")
    print()
    print("Skipping DB-dependent analysis until ported.")
    return


if __name__ == "__main__":
    main()
