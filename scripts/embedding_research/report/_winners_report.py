"""Active catalog winners & factors report section.

Research-only.  Renders the deterministic catalog winner/delta and factor rosters
(computed by ``_winners.py``) as per-backbone subsections of the ``winners`` schema-v2
section.  Populations are per-backbone and never cross-averaged.
"""

from __future__ import annotations

import pandas as pd

from ._base import make_section, make_table
from ._winners import build_factor_rows, build_winner_delta_rows


def _cell_rows(winner_df: pd.DataFrame, backbone: str) -> list[dict]:
    sub = winner_df[winner_df["backbone"] == backbone]
    rows: list[dict] = []
    for _, r in sub.iterrows():
        rows.append(
            {
                "sim_metric": r["sim_metric"],
                "k": int(r["k"]),
                "metric": r["metric"],
                "n_classes": int(r["n_classes"]),
                "baseline_strategy_key": r["baseline_strategy_key"],
                "baseline_canonical_config_id": _maybe_int(r.get("baseline_canonical_config_id")),
                "baseline_value": float(r["baseline_value"]),
                "winner_strategy_key": r["winner_strategy_key"],
                "winner_canonical_config_id": _maybe_int(r.get("winner_canonical_config_id")),
                "winner_alias_ids": _alias_text(r.get("winner_alias_ids")),
                "winner_value": float(r["winner_value"]),
                "delta": float(r["delta"]),
            }
        )
    return rows


def _factor_rows(factor_df: pd.DataFrame, backbone: str) -> list[dict]:
    sub = factor_df[factor_df["backbone"] == backbone]
    rows: list[dict] = []
    for _, r in sub.iterrows():
        rows.append(
            {
                "score_variant": r["score_variant"],
                "scoring_semantics_version": int(r["scoring_semantics_version"]),
                "strategy_key": r["strategy_key"],
                "sim_metric": r["sim_metric"],
                "k": int(r["k"]),
                "canonical_config_id": _maybe_int(r.get("canonical_config_id")),
                "alias_ids": _alias_text(r.get("alias_ids")),
                "representation_hash": r.get("representation_hash"),
                "view_keyset_hash": r.get("view_keyset_hash"),
                "catalog_id": r.get("catalog_id"),
            }
        )
    return rows


_INCOMPLETE_COLUMNS = [
    "strategy_key",
    "sim_metric",
    "k",
    "metric",
    "baseline_strategy_key",
    "reason",
    "baseline_evaluation_corpus_hash",
    "baseline_evaluation_corpus_count",
    "baseline_evaluation_corpus_comparable",
    "representation_evaluation_corpus_hash",
    "representation_evaluation_corpus_count",
    "representation_evaluation_corpus_comparable",
    "representation_missing_count",
    "representation_missing_digest",
    # Plan B P2 enrichment (persisted non-comparable diagnostics only; a derive-path unequal/
    # baseline-match incomplete entry renders these blank): the tested class's durable SEMANTIC
    # representation hash + canonical config id + full tested-threshold membership, and the
    # actual lost-song membership (observation evidence) — so the diagnostic shows WHICH tested
    # class lost songs and HOW MANY / WHICH eligible songs.
    "search_representation_hash",
    "canonical_config_id",
    "config_ids",
    "missing_song_ids",
]


def _incomplete_rows(winner_df: pd.DataFrame, backbone: str) -> list[dict]:
    """Render the matched-only-excluded incomplete diagnostics for *backbone* as row dicts.

    Reads ``winner_df.attrs["baseline_incomplete"]`` (the ``BaselineDeltaResult.incomplete``
    tuples carried across the winners DataFrame boundary by ``build_winner_delta_rows``) and maps
    each to the :data:`_INCOMPLETE_COLUMNS` row shape so a partial / non-comparable / unequal
    representation is VISIBLY surfaced in the winners section (never silently absent).
    """
    out: list[dict] = []
    for entry in winner_df.attrs.get("baseline_incomplete", ()) if winner_df is not None else ():
        if str(entry.get("backbone")) != backbone:
            continue
        out.append(
            {
                "strategy_key": entry.get("strategy_key"),
                "sim_metric": entry.get("sim_metric"),
                "k": entry.get("k"),
                "metric": entry.get("metric"),
                "baseline_strategy_key": entry.get("baseline_strategy_key"),
                "reason": entry.get("reason"),
                "baseline_evaluation_corpus_hash": entry.get("baseline_evaluation_corpus_hash"),
                "baseline_evaluation_corpus_count": entry.get("baseline_evaluation_corpus_count"),
                "baseline_evaluation_corpus_comparable": entry.get("baseline_evaluation_corpus_comparable"),
                "representation_evaluation_corpus_hash": entry.get("representation_evaluation_corpus_hash"),
                "representation_evaluation_corpus_count": entry.get("representation_evaluation_corpus_count"),
                "representation_evaluation_corpus_comparable": entry.get("representation_evaluation_corpus_comparable"),
                "representation_missing_count": entry.get("representation_missing_count"),
                "representation_missing_digest": entry.get("representation_missing_digest"),
                "search_representation_hash": entry.get("search_representation_hash"),
                "canonical_config_id": entry.get("canonical_config_id"),
                "config_ids": _alias_text(entry.get("config_ids")),
                "missing_song_ids": _alias_text(entry.get("missing_song_ids")),
            }
        )
    return out


def _alias_text(v) -> str:
    if not v:
        return "—"
    return ",".join(str(a) for a in v)


def _maybe_int(v):
    if v is None or pd.isna(v):
        return None
    return int(v)


def section_winners(analysis_df: pd.DataFrame) -> dict:
    """Render deterministic catalog winner/delta and factor tables per backbone."""
    if analysis_df is None or analysis_df.empty:
        return make_section(
            "winners",
            "Catalog Winners & Deltas",
            empty_message="No active catalog analysis results. Run the analyze phase.",
        )

    winner_df = build_winner_delta_rows(analysis_df)
    factor_df = build_factor_rows(analysis_df)
    backbones = sorted({str(b) for b in analysis_df["backbone"].dropna().tolist()})
    subsections: list[dict] = []
    for backbone in backbones:
        cells = _cell_rows(winner_df, backbone)
        factors = _factor_rows(factor_df, backbone)
        incomplete = _incomplete_rows(winner_df, backbone)
        tables = []
        if cells:
            tables.append(
                make_table(
                    cells,
                    id=f"winner_delta_{backbone}",
                    title=f"Exact winners, deltas & baselines ({backbone})",
                    summary_text=f"{len(cells)} winner cell(s)",
                )
            )
        if factors:
            tables.append(
                make_table(
                    factors,
                    id=f"factor_classes_{backbone}",
                    title=f"Active catalog class factors ({backbone})",
                    summary_text=f"{len(factors)} factor row(s)",
                    open=False,
                )
            )
        if incomplete:
            tables.append(
                make_table(
                    incomplete,
                    id=f"incomplete_representations_{backbone}",
                    title=f"Incomplete / non-comparable representations ({backbone})",
                    summary_text=f"{len(incomplete)} representation(s) excluded from matched deltas",
                )
            )
        if not tables:
            continue
        subsections.append(
            {
                "id": f"winners-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [{"label": "winner cells", "value": len(cells)}],
                "charts": [],
                "tables": tables,
                "panels": [],
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    if not subsections:
        return make_section(
            "winners",
            "Catalog Winners & Deltas",
            empty_message="No finite winner cells across the active catalog results.",
        )

    return make_section(
        "winners",
        "Catalog Winners & Deltas",
        description=(
            "Deterministic per-(sim_metric, k, metric) winner/delta tables and per-class "
            "factor rosters, rendered separately for each backbone.  baseline = the observed "
            "global-medoid baseline (global_pool:{backbone}:medoid) scored over the same "
            "corpus / sim_metric / k / metric, never a winner candidate; winner = the highest "
            "finite catalog-class value with strategy_key tie-break; delta = winner - baseline.  "
            "Each factor row renders the class's DURABLE SEMANTIC representation_hash distinctly "
            "from its DISPOSABLE view_keyset_hash plus catalog anchor.  Equal representations were "
            "collapsed to one class by the analyze pipeline, so alias lists never create duplicate "
            "score rows.  A partial / non-comparable / unequal representation is never a matched "
            "winner: it is excluded from the winner/delta table and rendered explicitly in the "
            "per-backbone incomplete-representations table (with its reason and corpus/missing "
            "evidence)."
        ),
        subsections=subsections,
    )
