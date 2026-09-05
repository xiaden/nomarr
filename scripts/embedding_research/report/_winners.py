"""Deterministic catalog winner / delta / factor row builders.

Research-only.  Consumes the *decoded* catalog long-form frame produced by
``_retrieval.query_analyze_metrics`` and emits, per ``(backbone, sim_metric, k, metric)``
cell, the deterministic baseline and winner of the active collapsed classes plus their
delta.  Populations are per-backbone and never cross-averaged.

Selection rules (binding, see the frozen-amendment contract):

* **baseline** — the active catalog class with the lowest ``(canonical_config_id,
  strategy_key)`` after collapse.  When no provenance config identity is present the
  deterministic ``strategy_key`` order decides.  An obsolete flat baseline is never
  synthesised.
* **winner** — the active class with the highest *finite* metric value; ties break to the
  lowest ``strategy_key``.
* **delta** = ``winner_value - baseline_value`` (finite, same backbone x sim_metric x k x metric).

Equal search representations were collapsed to one class by the analyze pipeline (each
class scored once), so every cell's classes are already distinct; alias lists ride along on
winner/factor rows and never create duplicate score rows.
"""

from __future__ import annotations

import math

import pandas as pd

# ---------------------------------------------------------------------------
# Active catalog vocabulary
# ---------------------------------------------------------------------------

#: Columns emitted by :func:`build_winner_delta_rows` (one row per
#: ``(backbone, sim_metric, k, metric)`` cell with a finite candidate).
CATALOG_WINNER_DELTA_COLUMNS: list[str] = [
    "backbone",
    "sim_metric",
    "k",
    "metric",
    "n_classes",
    "baseline_strategy_key",
    "baseline_canonical_config_id",
    "baseline_value",
    "winner_strategy_key",
    "winner_canonical_config_id",
    "winner_alias_ids",
    "winner_value",
    "delta",
]

#: Columns emitted by :func:`build_factor_rows` (one compact active-dimension row per
#: distinct ``(backbone, strategy_key, sim_metric, k)`` class present in the analysis).
CATALOG_FACTOR_COLUMNS: list[str] = [
    "backbone",
    "score_variant",
    "scoring_semantics_version",
    "strategy_key",
    "sim_metric",
    "k",
    "canonical_config_id",
    "alias_ids",
    "representation_hash",
]

#: Large sentinel used to order classes without a provenance config id after classes that
#: have one (they still sort deterministically by strategy_key among themselves).
_MISSING_CONFIG_SENTINEL = 10**12


def _is_finite_value(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
    return False


def build_winner_delta_rows(analysis_df: pd.DataFrame) -> pd.DataFrame:
    """Per-(backbone, sim_metric, k, metric) deterministic baseline/winner/delta rows."""
    columns = list(CATALOG_WINNER_DELTA_COLUMNS)
    if analysis_df is None or analysis_df.empty:
        return pd.DataFrame(columns=columns)

    recs = analysis_df[
        ["backbone", "sim_metric", "k", "metric", "strategy_key", "value", "canonical_config_id", "alias_ids"]
    ].to_dict("records")

    cells: dict[tuple[str, str, int, str], list[dict]] = {}
    for r in recs:
        key = (str(r["backbone"]), str(r["sim_metric"]), int(r["k"]), str(r["metric"]))
        cells.setdefault(key, []).append(r)

    out: list[dict] = []
    for key in sorted(cells):
        rows = cells[key]
        finite = [r for r in rows if _is_finite_value(r.get("value"))]
        if not finite:
            continue
        n_classes = len(rows)

        def baseline_sort(r: dict) -> tuple[int, str]:
            cc = r.get("canonical_config_id")
            ck = cc if isinstance(cc, int) else _MISSING_CONFIG_SENTINEL
            return (ck, str(r["strategy_key"]))

        baseline = min(finite, key=baseline_sort)

        def winner_sort(r: dict) -> tuple[float, str]:
            return (-float(r["value"]), str(r["strategy_key"]))

        winner = min(finite, key=winner_sort)
        bv = float(baseline["value"])
        wv = float(winner["value"])
        out.append(
            {
                "backbone": str(winner["backbone"]),
                "sim_metric": str(winner["sim_metric"]),
                "k": int(winner["k"]),
                "metric": str(winner["metric"]),
                "n_classes": n_classes,
                "baseline_strategy_key": str(baseline["strategy_key"]),
                "baseline_canonical_config_id": _ccid(baseline.get("canonical_config_id")),
                "baseline_value": bv,
                "winner_strategy_key": str(winner["strategy_key"]),
                "winner_canonical_config_id": _ccid(winner.get("canonical_config_id")),
                "winner_alias_ids": _sorted_aliases(winner.get("alias_ids")),
                "winner_value": wv,
                "delta": wv - bv,
            }
        )

    if not out:
        return pd.DataFrame(columns=columns)
    order = ["backbone", "sim_metric", "k", "metric"]
    frame = pd.DataFrame(out)
    return frame.sort_values(order, kind="mergesort").reset_index(drop=True)


def build_factor_rows(analysis_df: pd.DataFrame) -> pd.DataFrame:
    """Compact active-dimension roster of every catalog class present in the analysis.

    One row per distinct ``(backbone, strategy_key, sim_metric, k)`` class; carries the
    decoded active dimensions (score_variant / scoring_semantics_version / representation
    hash), the canonical config id, and the sorted alias list — no per-metric duplication.
    """
    columns = list(CATALOG_FACTOR_COLUMNS)
    if analysis_df is None or analysis_df.empty:
        return pd.DataFrame(columns=columns)

    need = [
        "backbone",
        "strategy_key",
        "sim_metric",
        "k",
        "score_variant",
        "scoring_semantics_version",
        "representation_hash",
        "canonical_config_id",
        "alias_ids",
    ]
    recs = analysis_df[need].to_dict("records")

    seen: set[tuple[str, str, str, int]] = set()
    out: list[dict] = []
    for r in recs:
        sk = str(r["strategy_key"])
        backbone = str(r["backbone"])
        sim = str(r["sim_metric"])
        kk = int(r["k"])
        dedup = (backbone, sk, sim, kk)
        if dedup in seen:
            continue
        seen.add(dedup)
        out.append(
            {
                "backbone": backbone,
                "score_variant": str(r["score_variant"]),
                "scoring_semantics_version": int(r["scoring_semantics_version"]),
                "strategy_key": sk,
                "sim_metric": sim,
                "k": kk,
                "canonical_config_id": _ccid(r.get("canonical_config_id")),
                "alias_ids": _sorted_aliases(r.get("alias_ids")),
                "representation_hash": str(r["representation_hash"]),
            }
        )

    if not out:
        return pd.DataFrame(columns=columns)
    order = ["backbone", "sim_metric", "k", "strategy_key"]
    frame = pd.DataFrame(out)
    return frame.sort_values(order, kind="mergesort").reset_index(drop=True)


def _ccid(v) -> int | None:
    return int(v) if isinstance(v, int) else (int(v) if isinstance(v, (float,)) and not pd.isna(v) else None)


def _sorted_aliases(v) -> list[int]:
    if not v:
        return []
    out: list[int] = []
    for a in v:
        try:
            out.append(int(a))
        except (TypeError, ValueError):
            continue
    return sorted(out)


__all__ = [
    "CATALOG_FACTOR_COLUMNS",
    "CATALOG_WINNER_DELTA_COLUMNS",
    "build_factor_rows",
    "build_winner_delta_rows",
]
