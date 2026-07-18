#!/usr/bin/env python3
"""Head calibration + STD gate audit.

For every (head, label) pair this script reports:
  - Raw mean/std distribution (p25/p50/p75/p90/p95/max)
  - Calibration p5, p95, and the resulting scale factor 1/(p95-p5)
  - Gate simulation: fraction of files that would be fully gated out vs capped
    at low/medium vs allowed through to high — using the *current* thresholds
    (acceptable=0.25, stable=0.15, very_stable=0.08)
  - Current tier hit counts (strict / regular / loose) pulled from the tag table
  - Distribution shape (bimodal / compressed / skewed / bell) inferred from means
  - Calibration method recommendation per shape

Queries the PostgreSQL persistence layer (calibration_states, tags,
ml_model_outputs) via the ``Database`` facade.

Usage:
    .venv/Scripts/python.exe scripts/diagnostics/head_calibration_audit.py
    .venv/Scripts/python.exe scripts/diagnostics/head_calibration_audit.py --db-url postgresql+asyncpg://user:pass@host:5432/nomarr
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import defaultdict

import numpy as np
from scipy import stats as spstats

from nomarr.persistence.db import Database

# ── defaults ────────────────────────────────────────────────────────────────

DEFAULT_DB_URL = "postgresql+asyncpg://nomarr:nomarr@localhost:5432/nomarr"

# Stability thresholds — must match tagging_aggregation_comp.py DEFAULT_STABILITY_THRESHOLDS
GATE_ACCEPTABLE = 0.25
GATE_STABLE = 0.15
GATE_VERY_STABLE = 0.08

# ── CLI ─────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help="PostgreSQL connection URL (asyncpg driver).  Default: %(default)s",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show per-state segment-stat detail (p25/p50/p75/p90/p95).",
    )
    p.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress per-state output; show summary only.",
    )
    return p.parse_args()


# ── data extraction helpers ─────────────────────────────────────────────────


def _extract_segment_arrays(
    output_data: dict,
    target_label: str | None = None,
) -> tuple[list[float], list[float]]:
    """Extract per-segment means and stds from stored model output JSON.

    Handles several common output_data shapes produced by the inference
    pipeline.  Returns ``(means, stds)`` — both may be empty if no
    segment data is found.

    Shapes accepted:

    * ``{"segments": [{"mean": …, "std": …}, …]}``
    * ``{"segment_stats": {"means": […], "stds": […]}}``
    * ``{"means": […], "stds": […]}}``
    * ``{"segment_means": […], "segment_stds": […]}}``
    """
    means: list[float] = []
    stds: list[float] = []

    # Shape 1: list of per-segment dicts with "mean" / "std"
    segments = output_data.get("segments")
    if isinstance(segments, list):
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            m_val = seg.get("mean")
            s_val = seg.get("std")
            if m_val is not None:
                means.append(float(m_val))
            if s_val is not None:
                stds.append(float(s_val))
        if means:
            return means, stds

    # Shape 2: nested "segment_stats"
    seg_stats = output_data.get("segment_stats")
    if isinstance(seg_stats, dict):
        m_arr = seg_stats.get("means")
        s_arr = seg_stats.get("stds")
        if isinstance(m_arr, list):
            means = [float(v) for v in m_arr]
        if isinstance(s_arr, list):
            stds = [float(v) for v in s_arr]
        if means or stds:
            return means, stds

    # Shape 3: top-level "means" / "stds" keys
    m_arr = output_data.get("means")
    s_arr = output_data.get("stds")
    if isinstance(m_arr, list):
        means = [float(v) for v in m_arr]
    if isinstance(s_arr, list):
        stds = [float(v) for v in s_arr]
    if means or stds:
        return means, stds

    # Shape 4: "segment_means" / "segment_stds"
    m_arr = output_data.get("segment_means")
    s_arr = output_data.get("segment_stds")
    if isinstance(m_arr, list):
        means = [float(v) for v in m_arr]
    if isinstance(s_arr, list):
        stds = [float(v) for v in s_arr]

    return means, stds


# ── distribution shape ───────────────────────────────────────────────────────


def classify_distribution(means: np.ndarray) -> tuple[str, str]:
    """Returns (shape_label, calibration_recommendation).

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
    """Returns fraction of files in each gate bucket.
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


# ── tag tier reporting ──────────────────────────────────────────────────────


async def _fetch_tier_counts(db: Database) -> dict[str, int]:
    """Count tags per tier level in the ``tags`` table.

    Returns a dict like ``{"strict": N, "regular": N, "loose": N, "other": N}``.
    """
    from sqlalchemy import func, select

    from nomarr.persistence.models.tag import Tag

    _tbl = Tag.__table__  # type: ignore[assignment]
    stmt = (
        select(_tbl.c.tier, func.count().label("cnt"))
        .where(
            _tbl.c.tier.isnot(None),
        )
        .group_by(_tbl.c.tier)
    )
    counts: dict[str, int] = {"strict": 0, "regular": 0, "loose": 0, "other": 0}
    tier_labels = {1: "strict", 2: "regular", 3: "loose"}

    # Use the Database's session-maker to create a session for raw SQL.
    async with db._pg_session() as session:
        result = await session.execute(stmt)
        for row in result.all():
            tier_int = row[0]
            cnt = int(row[1])
            key = tier_labels.get(tier_int, "other")
            counts[key] += cnt

    return counts


# ── main ─────────────────────────────────────────────────────────────────────


async def main() -> None:
    args = parse_args()
    logging.getLogger("head_calibration_audit")
    logging.basicConfig(level=logging.WARNING)  # keep DB chatter quiet

    db = Database(url=args.db_url)

    try:
        # ── 0. Tag tier counts ──────────────────────────────────────────
        await _fetch_tier_counts(db)
        if not args.quiet:
            for _tier_name in ("strict", "regular", "loose", "other"):
                pass

        # ── 1. Calibration states ───────────────────────────────────────
        states = await db.ml.list_all_calibration_states_with_models()
        if not states:
            return

        # ── 2. Per-state analysis ───────────────────────────────────────
        report_lines: list[dict] = []
        head_groups: dict[str, list[dict]] = defaultdict(list)

        for idx, state in enumerate(states, 1):
            sd = state.get("state_data", {})
            if not isinstance(sd, dict):
                continue

            head_name = sd.get("head_name", "unknown")
            label = sd.get("label", "unknown")
            p5 = float(sd.get("p5", 0.0))
            p95 = float(sd.get("p95", 1.0))
            cal_n = int(sd.get("n", 0))
            model_id = state.get("model_id", "")

            # Compute scale factor
            span = p95 - p5
            scale = 1.0 / span if span > 1e-9 else 1.0

            # ── Fetch segment scores ─────────────────────────────────
            seg_means: list[float] = []
            seg_stds: list[float] = []
            if model_id:
                outputs = await db.ml.list_model_outputs(model_id)
                for out in outputs:
                    od = out.get("output_data", {})
                    if not isinstance(od, dict):
                        continue
                    # If the output has a label column, filter by it
                    out_label = out.get("label")
                    if out_label is not None and out_label != label:
                        continue
                    # Also check output_data's own label field
                    od_label = od.get("label")
                    if od_label is not None and out_label is None and od_label != label:
                        continue
                    em, es = _extract_segment_arrays(od, target_label=label)
                    seg_means.extend(em)
                    seg_stds.extend(es)

            means_arr = np.array(seg_means, dtype=np.float64)
            stds_arr = np.array(seg_stds, dtype=np.float64)

            # ── Distribution shape ────────────────────────────────────
            shape_label, recommendation = classify_distribution(means_arr)

            # ── Percentiles ───────────────────────────────────────────
            pct_display: dict[str, float | str] = {}
            if len(means_arr) >= 1:
                pcts = np.percentile(means_arr, [25, 50, 75, 90, 95]) if len(means_arr) >= 4 else []
                if len(pcts) >= 3:
                    pct_display = {
                        "p25": round(float(pcts[0]), 3),
                        "p50": round(float(pcts[1]), 3),
                        "p75": round(float(pcts[2]), 3),
                        "p90": round(float(pcts[3]), 3) if len(pcts) >= 4 else "-",
                        "p95": round(float(pcts[4]), 3) if len(pcts) >= 5 else "-",
                        "max": round(float(means_arr.max()), 3),
                    }

            # ── Gate simulation ───────────────────────────────────────
            gates = simulate_gates(stds_arr, scale)

            # ── Sweeps ────────────────────────────────────────────────
            t_sweep = threshold_sweep(stds_arr, scale)
            e_sweep = exponent_sweep(stds_arr, scale)

            # ── Report ────────────────────────────────────────────────
            entry = {
                "head": head_name,
                "label": label,
                "p5": p5,
                "p95": p95,
                "scale": round(scale, 4),
                "n_files": cal_n,
                "n_segments": len(seg_means),
                "shape": shape_label,
                "recommendation": recommendation,
                "gates": gates,
                "threshold_sweep": t_sweep,
                "exponent_sweep": e_sweep,
                "percentiles": pct_display,
            }
            report_lines.append(entry)
            head_groups[head_name].append(entry)

            if not args.quiet:
                _print_state_report(idx, len(states), entry, verbose=args.verbose)

        # ── 3. Summary ─────────────────────────────────────────────────
        _print_summary(report_lines, head_groups)

    finally:
        await db.close()


def _print_state_report(
    idx: int,
    total: int,
    entry: dict,
    *,
    verbose: bool = False,
) -> None:
    """Print a single calibration-state report."""
    entry["gates"]

    # Show the most concerning sweep values
    t_sweep = entry["threshold_sweep"]
    e_sweep = entry["exponent_sweep"]
    if entry["shape"] == "bimodal":
        max(t_sweep.items(), key=lambda x: x[1])
    elif entry["shape"] == "compressed":
        worst_e = max(e_sweep.items(), key=lambda x: x[1])
        best_e = min(e_sweep.items(), key=lambda x: x[1])
        if best_e[0] != worst_e[0]:
            pass

    if verbose and entry["percentiles"]:
        entry["percentiles"]


def _print_summary(
    report_lines: list[dict],
    head_groups: dict[str, list[dict]],
) -> None:
    """Print a summary table of all heads and their labels."""
    if not report_lines:
        return

    shape_counts: dict[str, int] = defaultdict(int)
    for entry in report_lines:
        shape_counts[entry["shape"]] += 1

    # Flag concerning states
    concerns = [e for e in report_lines if e["shape"] in ("compressed", "bimodal")]
    if concerns:
        for _e in concerns:
            pass

    # Highest none% per head group
    for head_name in sorted(head_groups):
        entries = head_groups[head_name]
        max(entries, key=lambda e: e["gates"]["none"])


# ── entry point ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    asyncio.run(main())
