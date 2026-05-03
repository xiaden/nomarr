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

Usage:
    .venv/Scripts/python.exe scripts/diagnostics/head_calibration_audit.py
    .venv/Scripts/python.exe scripts/diagnostics/head_calibration_audit.py --host http://127.0.0.1:8529 --password my_pass
"""

from __future__ import annotations

import argparse
import datetime
from collections import defaultdict
from pathlib import Path

import numpy as np
from arango import ArangoClient
from scipy import stats as spstats

# ── defaults ────────────────────────────────────────────────────────────────

DEFAULT_HOST = "http://127.0.0.1:8529"
DEFAULT_DB   = "nomarr"
DEFAULT_USER = "root"
DEFAULT_PASS = "nomarr_dev_password"

# Stability thresholds — must match tagging_aggregation_comp.py DEFAULT_STABILITY_THRESHOLDS
GATE_ACCEPTABLE  = 0.25
GATE_STABLE      = 0.15
GATE_VERY_STABLE = 0.08

# ── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host",     default=DEFAULT_HOST, help="ArangoDB base URL")
    p.add_argument("--db",       default=DEFAULT_DB)
    p.add_argument("--user",     default=DEFAULT_USER)
    p.add_argument("--password", default=None,
                   help="Defaults to docker/.env ARANGO_ROOT_PASSWORD, then nomarr_dev_password")
    return p.parse_args()


def resolve_password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password
    env_file = Path(__file__).parents[2] / "docker" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ARANGO_ROOT_PASSWORD="):
                return line.split("=", 1)[1].strip()
    return DEFAULT_PASS


# ── AQL helpers ─────────────────────────────────────────────────────────────

def aql(db, query: str, **bind_vars) -> list:
    cursor = db.aql.execute(query, bind_vars=bind_vars or None, batch_size=10_000)
    return list(cursor)


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
    pct_low  = np.mean(means < 0.35)
    pct_high = np.mean(means > 0.65)

    # Bimodality coefficient (>0.555 suggests bimodal)
    sk = float(spstats.skew(means))
    ku = float(spstats.kurtosis(means))  # excess kurtosis
    n  = len(means)
    bc = (sk**2 + 1) / (ku + 3 * (n-1)**2 / ((n-2)*(n-3)))

    if iqr < 0.05:
        return "compressed",  "→ gate raw std (threshold *= cal_span); scale is the bug"
    if pct_low > 0.15 and pct_high > 0.15:
        return "bimodal",     "→ minmax OK; gate thresholds need raising (bimodal std is naturally high)"
    if bc > 0.555 and pct_low > 0.15 and pct_high > 0.15:
        return "bimodal",     "→ minmax OK; gate thresholds need raising"
    if q50 > 0.60:
        return "skewed-high", "→ minmax OK; consider raising gate thresholds"
    if q50 < 0.40:
        return "skewed-low",  "→ minmax OK; consider raising gate thresholds"
    return "bell",            "→ minmax OK"


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
    ss = raw_stds * (scale ** exponent)
    n  = len(ss)
    if n == 0:
        return {"full": 0.0, "med": 0.0, "low": 0.0, "none": 0.0}
    return {
        "full": float(np.mean(ss < GATE_VERY_STABLE)),
        "med":  float(np.mean((ss >= GATE_VERY_STABLE) & (ss < GATE_STABLE))),
        "low":  float(np.mean((ss >= GATE_STABLE)      & (ss < GATE_ACCEPTABLE))),
        "none": float(np.mean(ss >= GATE_ACCEPTABLE)),
    }


def threshold_sweep(raw_stds: np.ndarray, scale: float) -> dict[float, float]:
    """none% at each threshold in SWEEP_THRESHOLDS at exponent=1.0 (bimodal heads)."""
    ss = raw_stds * scale
    return {t: _none_pct(ss, t) for t in SWEEP_THRESHOLDS}


def exponent_sweep(raw_stds: np.ndarray, scale: float) -> dict[float, float]:
    """none% at acceptable=0.25 for each exponent in SWEEP_EXPONENTS (compressed heads)."""
    return {e: _none_pct(raw_stds * (scale ** e), GATE_ACCEPTABLE) for e in SWEEP_EXPONENTS}


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    args   = parse_args()
    passwd = resolve_password(args)

    print(f"Connecting to {args.host} db={args.db} user={args.user} …")
    client = ArangoClient(hosts=args.host)
    db     = client.db(args.db, username=args.user, password=passwd)
    print("Connected.\n")

    # ── 1. Pull all segment stats in one query ───────────────────────────────
    print("Fetching all segment_scores_stats …")
    rows = aql(db, """
        FOR s IN segment_scores_stats
          FOR ls IN s.label_stats
            RETURN {head: s.head_name, label: ls.label, mean: ls.mean, std: ls.std}
    """)
    print(f"  {len(rows):,} (head, label, mean, std) rows.\n")

    # Group by (head, label)
    grouped: dict[tuple[str,str], list[tuple[float,float]]] = defaultdict(list)
    for r in rows:
        grouped[(r["head"], r["label"])].append((r["mean"], r["std"]))

    # ── 2. Calibration state ─────────────────────────────────────────────────
    print("Fetching calibration_state …")
    calib_rows = aql(db, """
        FOR cs IN calibration_state
          RETURN {head: cs.head_name, label: cs.label,
                  p5: cs.p5, p95: cs.p95, n: cs.sample_count, version: cs.version}
    """)
    calib_map: dict[tuple[str,str], dict] = {
        (c["head"], c["label"]): c for c in calib_rows
    }
    print(f"  {len(calib_rows)} calibration records.\n")

    # ── 3. Tier hit counts ────────────────────────────────────────────────────
    print("Fetching tier hit counts (traversing song_has_tags) …")
    tier_rows = aql(db, """
        FOR t IN tags
          FILTER t.rel IN ["nom:mood-strict","nom:mood-regular","nom:mood-loose"]
          LET n = LENGTH(FOR e IN INBOUND t song_has_tags RETURN 1)
          RETURN {name: t.name, value: t.value, n: n}
    """)
    tier_hits: dict[str, dict[str,int]] = defaultdict(lambda: {"strict":0,"regular":0,"loose":0})
    for tr in tier_rows:
        key = tr["value"]
        if   tr["rel"] == "nom:mood-strict":  tier_hits[key]["strict"]  = tr["n"]
        elif tr["rel"] == "nom:mood-regular": tier_hits[key]["regular"] = tr["n"]
        elif tr["rel"] == "nom:mood-loose":   tier_hits[key]["loose"]   = tr["n"]
    print(f"  {len(tier_hits)} distinct mood terms with tier hits.\n")

    # ── 4. Build per-pair report ─────────────────────────────────────────────

    # Output to file too
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"head_calibration_audit_{ts}.txt"

    ANSI = {
        "red":     "\033[91m",
        "yellow":  "\033[93m",
        "magenta": "\033[95m",
        "cyan":    "\033[96m",
        "reset":   "\033[0m",
        "bold":    "\033[1m",
    }

    lines: list[tuple[str, str]] = []  # (text, color)

    def row(text: str, color: str = "") -> None:
        lines.append((text, color))

    # Column widths
    COL = dict(
        head=28, label=18, n=6,
        p50=6, p75=6, p90=6, p95=6, mxr=6,
        p5=6, p95c=6, scl=5,
        full=7, med=7, low=7, none=7,
        strict=7, regular=7, loose=7,
        shape=13, rec=38,
        mp10=6, mp50=6, mp90=6,
    )

    header = (
        f"{'HEAD':<{COL['head']}} {'LABEL':<{COL['label']}} {'N':>{COL['n']}}"
        f" | {'p50':>{COL['p50']}} {'p75':>{COL['p75']}} {'p90':>{COL['p90']}} {'p95':>{COL['p95']}} {'max':>{COL['mxr']}}"
        f" | {'cal_p5':>{COL['p5']}} {'cal_p95':>{COL['p95c']}} {'scale':>{COL['scl']}}"
        f" | {'full%':>{COL['full']}} {'med%':>{COL['med']}} {'low%':>{COL['low']}} {'none%':>{COL['none']}}"
        f" | {'strict':>{COL['strict']}} {'reg':>{COL['regular']}} {'loose':>{COL['loose']}}"
        f" | {'shape':<{COL['shape']}} {'cal_rec':<{COL['rec']}}"
        f"  mp10  mp50  mp90"
    )
    sep = "─" * len(header)

    row(f"# Head Calibration + STD Gate Audit — {datetime.datetime.now():%Y-%m-%d %H:%M}", "cyan")
    row(f"# Gates: acceptable={GATE_ACCEPTABLE}  stable={GATE_STABLE}  very_stable={GATE_VERY_STABLE}", "cyan")
    row("")
    row(sep)
    row(header, "bold")
    row(sep)

    problems_shape:  list[str] = []
    # (head, label) -> {threshold -> none_pct} for linear scale
    sweep_data: dict[tuple[str,str], dict[float, float]] = {}
    # (head, label) -> {exponent -> none_pct} — only populated for compressed heads
    exp_sweep_data: dict[tuple[str,str], dict[float, float]] = {}

    for (head, label) in sorted(grouped):
        pairs  = grouped[(head, label)]
        means  = np.array([p[0] for p in pairs], dtype=float)
        stds   = np.array([p[1] for p in pairs], dtype=float)
        n      = len(pairs)

        # Std percentiles
        p50r, p75r, p90r, p95r = np.percentile(stds, [50, 75, 90, 95])
        maxr = stds.max()

        # Mean percentiles
        mp10, mp50, mp90 = np.percentile(means, [10, 50, 90])

        # Calibration — calibration records store the *normalised* label
        # (non_X → not_X) so try both keys.
        norm_label = f"not_{label[4:]}" if label.startswith("non_") else label
        c = calib_map.get((head, norm_label)) or calib_map.get((head, label))
        if c and c["p5"] is not None and c["p95"] is not None:
            p5, p95c = float(c["p5"]), float(c["p95"])
            span  = p95c - p5
            scale = (1.0 / span) if span > 1e-9 else float("inf")
            cal_p5_s  = f"{p5:.4f}"
            cal_p95_s = f"{p95c:.4f}"
            scale_s   = f"{scale:.1f}x"
        else:
            p5 = p95c = scale = float("nan")
            span = float("nan")
            cal_p5_s = cal_p95_s = scale_s = "N/A"

        # Distribution shape — computed first; used by gate simulation
        shape, rec = classify_distribution(means)

        # Gate simulation — linear scale (current behaviour)
        if np.isfinite(scale):
            gates = simulate_gates(stds, scale)
            sweep_data[(head, label)] = threshold_sweep(stds, scale)
            if shape == "compressed":
                exp_sweep_data[(head, label)] = exponent_sweep(stds, scale)
        else:
            gates = {"full": 0.0, "med": 0.0, "low": 0.0, "none": 1.0}
            sweep_data[(head, label)] = dict.fromkeys(SWEEP_THRESHOLDS, 1.0)

        def pct(v: float) -> str:
            return f"{v*100:.1f}%"

        # Tier hits — try label name directly and with space instead of underscore
        mood_key = label.replace("_", " ")
        th = tier_hits.get(mood_key) or tier_hits.get(label) or {"strict":0,"regular":0,"loose":0}

        # Colour (based on current linear gating)
        color = ""
        if gates["none"] > 0.80:
            color = "red"
        elif gates["none"] > 0.40:
            color = "yellow"
        elif shape == "compressed":
            color = "magenta"
        if shape not in ("bell", "insufficient"):
            problems_shape.append(f"{head} / {label}: {shape} — {rec}")

        line = (
            f"{head:<{COL['head']}} {label:<{COL['label']}} {n:>{COL['n']}}"
            f" | {p50r:>{COL['p50']}.4f} {p75r:>{COL['p75']}.4f} {p90r:>{COL['p90']}.4f} {p95r:>{COL['p95']}.4f} {maxr:>{COL['mxr']}.4f}"
            f" | {cal_p5_s:>{COL['p5']}} {cal_p95_s:>{COL['p95c']}} {scale_s:>{COL['scl']}}"
            f" | {pct(gates['full']):>{COL['full']}} {pct(gates['med']):>{COL['med']}} {pct(gates['low']):>{COL['low']}} {pct(gates['none']):>{COL['none']}}"
            f" | {th['strict']:>{COL['strict']}} {th['regular']:>{COL['regular']}} {th['loose']:>{COL['loose']}}"
            f" | {shape:<{COL['shape']}} {rec:<{COL['rec']}}"
            f"  {mp10:.3f}  {mp50:.3f}  {mp90:.3f}"
        )
        row(line, color)

    row(sep)
    row("")

    # ── 5. Threshold sweep summary (bimodal 1x heads) ─────────────────────────
    # none% at acceptable=0.25…0.50. Reminder that pos/neg label pairs are
    # mutual-exclusion competitors — more songs surviving gating ≠ more tags
    # written; conflicting outcomes cancel each other out.
    sweep_header = (
        f"  {'HEAD / LABEL':<48}"
        + "".join(f"  @{t:.2f}" for t in SWEEP_THRESHOLDS)
    )
    row("── Threshold sweep (bimodal heads): none% at acceptable=0.25…0.50 ──", "yellow")
    row("  Note: pos/neg pairs compete — surviving gating ≠ tags written", "cyan")
    row(sweep_header, "bold")
    row("  " + "─" * (len(sweep_header) - 2))

    for (head, label) in sorted(sweep_data):
        sw = sweep_data[(head, label)]
        if sw[0.25] <= 0.20 or (head, label) in exp_sweep_data:
            continue  # skip low-gating and compressed heads
        key = f"{head} / {label}"
        cols = "".join(f"  {sw[t]*100:5.1f}%" for t in SWEEP_THRESHOLDS)
        row(f"  {key:<48}{cols}", "yellow")

    row("")

    # ── 6. Exponent sweep summary (compressed high-scale heads) ───────────────
    # none% at acceptable=0.25 as the scale exponent varies.
    # ^1.0 = current behaviour (full scale); pick where you want the curve.
    if exp_sweep_data:
        exp_header = (
            f"  {'HEAD / LABEL':<48}"
            + "".join(f"  ^{e:.2f}" for e in SWEEP_EXPONENTS)
        )
        row("── Scale exponent sweep (compressed heads): none% at acceptable=0.25,  ^1.0=current ──", "magenta")
        row(exp_header, "bold")
        row("  " + "─" * (len(exp_header) - 2))
        for (head, label) in sorted(exp_sweep_data):
            es  = exp_sweep_data[(head, label)]
            key = f"{head} / {label}"
            cols = "".join(f"  {es[e]*100:5.1f}%" for e in SWEEP_EXPONENTS)
            row(f"  {key:<48}{cols}", "magenta")
        row("")

    row("── Calibration method mismatch (non-bell distributions) ──", "magenta")
    if problems_shape:
        for p in sorted(set(problems_shape)):
            row(f"  {p}", "magenta")
    else:
        row("  (none)", "magenta")
    row("")

    # ── 6. Print + write ─────────────────────────────────────────────────────
    file_lines: list[str] = []
    for text, color in lines:
        code = ANSI.get(color, "")
        reset = ANSI["reset"] if code else ""
        print(f"{code}{text}{reset}")
        file_lines.append(text)

    out_path.write_text("\n".join(file_lines), encoding="utf-8")
    print(f"\nReport saved to: {out_path}")


if __name__ == "__main__":
    main()
