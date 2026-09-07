"""Deterministic catalog winner / delta / factor row builders.

Research-only.  Consumes the *decoded* winners/summary long-form frame (catalog classes PLUS
the per-backbone observed ``global_pool:{backbone}:medoid`` baseline rows — see
``_retrieval.query_winners_metrics``) and emits, per ``(backbone, sim_metric, k, metric)``
cell, the deterministic observed-medoid baseline and winner of the active collapsed classes
plus their delta.  Populations are per-backbone and never cross-averaged.

Selection rules (binding, see the frozen-amendment contract):

* **baseline** — the observed global-medoid baseline for that backbone/cell: the
  ``global_pool:{backbone}:medoid`` row scored under the SAME corpus / sim_metric / k /
  metric as the segmented classes.  The medoid is NEVER a winner candidate.  A cell whose
  scope lacks a finite medoid baseline row emits nothing (no phantom delta); a present
  non-finite value fails closed.
* **winner** — the active catalog class with the highest *finite* metric value; ties break
  to the lowest ``strategy_key``.
* **delta** = ``winner_value - baseline_value`` (finite, same backbone x sim_metric x k x metric).

Cell selection is delegated to ``baseline.build_baseline_delta_rows`` and remapped to the
report's winner/delta columns (see :func:`build_winner_delta_rows`).

Equal search representations were collapsed to one class by the analyze pipeline (each
class scored once), so every cell's classes are already distinct; alias lists ride along on
winner/factor rows and never create duplicate score rows.
"""

from __future__ import annotations

import pandas as pd

from scripts.embedding_research.baseline import build_baseline_delta_rows

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
    "view_keyset_hash",
    "catalog_id",
]


def build_winner_delta_rows(analysis_df: pd.DataFrame) -> pd.DataFrame:
    """Per-(backbone, sim_metric, k, metric) observed-medoid baseline/winner/delta rows.

    Consumes the enriched winners/summary frame (catalog classes + per-cell observed medoid
    baseline rows), delegates cell baseline/winner/delta selection to
    :func:`baseline.build_baseline_delta_rows`, and remaps the MATCHED ``rows`` of its
    structured :class:`~scripts.embedding_research.baseline.BaselineDeltaResult` to the report
    :data:`CATALOG_WINNER_DELTA_COLUMNS` shape (``n_segmented_classes`` -> ``n_classes``, with
    ``baseline_canonical_config_id = None`` because the medoid baseline is not a config class).
    Matching-only semantics (equal/comparable/finite evaluation corpus) are enforced inside the
    delegated builder; representations that cannot match produce no winner/delta row here and are
    surfaced as that builder's ``incomplete`` diagnostics.

    The returned winner/delta frame carries ONLY matched cells (an incomplete / non-comparable /
    unequal representation NEVER renders as a matched complete metric).  The full structured
    incompleteness diagnostics from :attr:`BaselineDeltaResult.incomplete` — per-cell reason,
    the baseline vs. representation corpus hash/count/comparability and the representation's
    missing-song digest — are preserved on ``frame.attrs["baseline_incomplete"]`` as the tuple of
    diagnostic mappings, so summary/winners rendering can surface partial representations without
    ever counting them as matched.  A cell with no observed medoid baseline row in scope emits nothing.
    """
    columns = list(CATALOG_WINNER_DELTA_COLUMNS)
    if analysis_df is None or analysis_df.empty:
        out = pd.DataFrame(columns=columns)
        out.attrs["baseline_incomplete"] = ()
        return out

    base = build_baseline_delta_rows(analysis_df)
    if not base.rows:
        out = pd.DataFrame(columns=columns)
        out.attrs["baseline_incomplete"] = tuple(base.incomplete)
        return out

    out = pd.DataFrame(list(base.rows)).rename(columns={"n_segmented_classes": "n_classes"})
    out["baseline_canonical_config_id"] = None
    # Reorder to the report's canonical winner/delta column contract.
    out = out.reindex(columns=columns).reset_index(drop=True)
    out.attrs["baseline_incomplete"] = tuple(base.incomplete)
    return out


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
        "view_keyset_hash",
        "catalog_id",
        "canonical_config_id",
        "alias_ids",
    ]
    recs = analysis_df[need].to_dict("records")
    # Only catalog classes are factors.  An observed ``global_pool:{backbone}:medoid`` baseline
    # row is NOT a config class and never appears in the factor roster (it carries no config
    # identity / representation hash of its own).
    recs = [r for r in recs if str(r["strategy_key"]).startswith("catalog:")]

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
                "representation_hash": str(r["representation_hash"]) if r.get("representation_hash") else None,
                "view_keyset_hash": str(r["view_keyset_hash"]) if r.get("view_keyset_hash") else "",
                "catalog_id": str(r["catalog_id"]) if r.get("catalog_id") else None,
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
