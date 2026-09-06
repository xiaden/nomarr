"""Active catalog-only analysis loader and analysis section builder.

Research-only.  This module owns the single active reader over ``analyze_metrics``:

* :func:`query_analyze_metrics` returns the run-scoped (or whole active-table) catalog
  analysis rows as a decoded long-form frame.  Only ``strategy_type == "catalog"`` rows are
  ever read — there is no legacy strategy allowlist.  Each row is one literal
  ``(strategy_key, sim_metric, k, metric, value)`` cell of an active catalog class,
  enriched with the decoded identity and the provenance-scope fields
  (``canonical_config_id`` / ``alias_ids`` / ``view_content_hash``) read from the analyze
  run scope recorded in ``run_provenance``.
* :func:`query_medoid_baselines` returns the observed ``global_pool:{backbone}:medoid``
  baseline ``analyze_metrics`` rows (``strategy_type == "global_pool"``) as a decoded frame.
* :func:`query_winners_metrics` concatenates the catalog classes with those medoid baseline
  rows into the winners/summary frame (catalog classes plus per-backbone baselines).
* :func:`section_analysis` renders those rows into the ``analysis`` schema-v2 section, one
  per-backbone subsection.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from scripts.embedding_research.baseline import MEDOID_STRATEGY_TYPE
from scripts.embedding_research.db.analyze_scope import parse_analyze_scope

from ._base import (
    CATALOG_ANALYSIS_COLUMNS,
    CATALOG_STRATEGY_TYPE,
    decode_catalog_strategy_key,
    empty_df,
    fmt,
    make_section,
    make_table,
    table_exists,
)


def _scope_map(con, *, run_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Map catalog strategy_key -> analyze run-scope dict from ``run_provenance``.

    Reads ``phase='analyze'`` provenance rows' ``output_artifact_hashes`` and parses each
    canonical ``analyze_scope_v1`` line (:func:`parse_analyze_scope`).  When *run_id* is given
    only that run's provenance rows are scanned, else every analyze provenance row is scanned
    (the whole active completed scope).  Returns ``{strategy_key: scope}``.
    """
    out: dict[str, dict[str, Any]] = {}
    if not table_exists(con, "run_provenance"):
        return out
    params: tuple[str, ...] = ()
    where = ""
    if run_id is not None:
        where = " WHERE run_id = ? AND phase = ?"
        params = (run_id, "analyze")
    else:
        where = " WHERE phase = ?"
        params = ("analyze",)
    try:
        rows = con.execute(
            "SELECT output_artifact_hashes FROM run_provenance" + where,
            list(params),
        ).fetchall()
    except Exception:
        return out
    for (blob,) in rows:
        if not blob:
            continue
        for line in blob.splitlines():
            scope = parse_analyze_scope(line.strip())
            if scope is None:
                continue
            out.setdefault(scope["strategy_key"], scope)
    return out


def _alias_and_canonical(config_ids: Any) -> tuple[Any, list[Any]]:
    """Split a sorted class member list into (canonical_config_id, sorted alias_ids).

    ``config_ids`` is the ascending class member list with the canonical (lowest) member
    first.  Empty / absent membership yields ``(None, [])``.
    """
    if not config_ids:
        return None, []
    ids = [int(c) for c in config_ids]
    return ids[0], sorted(ids[1:])


def query_analyze_metrics(
    con,
    *,
    run_id: str | None = None,
) -> pd.DataFrame:
    """Load the active catalog-only ``analyze_metrics`` rows as a decoded long frame.

    Reads every ``analyze_metrics`` row with ``strategy_type == 'catalog'`` (optionally
    restricted to the physical ``run_id`` column equalling *run_id*), decodes each active
    ``catalog:{backbone}:{score_variant}:v{version}:{keyset}`` strategy key, and enriches the
    row with the provenance-scope config identity (``canonical_config_id``, sorted
    ``alias_ids``) and ``view_content_hash`` where the analyze run scope is recorded.

    Returns an empty frame with :data:`CATALOG_ANALYSIS_COLUMNS` when the table is absent,
    has no catalog rows, or a query fails (so callers render empty sections rather than crash).
    """
    columns = list(CATALOG_ANALYSIS_COLUMNS)
    if not table_exists(con, "analyze_metrics"):
        return empty_df(columns)

    params: list[object] = [CATALOG_STRATEGY_TYPE]
    where_run = ""
    if run_id is not None:
        where_run = " AND run_id = ?"
        params.append(run_id)
    try:
        df = con.execute(
            "SELECT run_id, strategy_key, strategy_type, sim_metric, k, metric, value "
            "FROM analyze_metrics WHERE strategy_type = ?" + where_run,
            params,
        ).df()
    except Exception:
        return empty_df(columns)

    if df.empty:
        return empty_df(columns)

    # Decode the active catalog identity; rows whose key is not a well-formed catalog key are
    # dropped (a data-integrity anomaly, never a strategy-filter).
    decoded = df["strategy_key"].map(decode_catalog_strategy_key)
    valid = decoded.notna()
    if not valid.all():
        df = df.loc[valid]
    if df.empty:
        return empty_df(columns)

    identity = pd.DataFrame(
        list(decoded.loc[valid]),
        index=df.index,
    )

    scope = _scope_map(con, run_id=run_id)
    canonical: list[Any] = []
    alias_ids: list[Any] = []
    view_hashes: list[Any] = []
    for key in df["strategy_key"]:
        cfg = scope.get(key)
        ccid, aliases = _alias_and_canonical(cfg.get("config_ids") if cfg else None)
        canonical.append(ccid)
        alias_ids.append(aliases)
        view_hashes.append(cfg.get("view_content_hash") if cfg else None)

    enriched = pd.DataFrame(
        {
            "run_id": df["run_id"],
            "backbone": identity["backbone"],
            "strategy_key": df["strategy_key"],
            "strategy_type": CATALOG_STRATEGY_TYPE,
            "sim_metric": df["sim_metric"],
            "k": df["k"],
            "score_variant": identity["score_variant"],
            "scoring_semantics_version": identity["scoring_semantics_version"],
            "representation_hash": identity["keyset_hash"],
            "canonical_config_id": canonical,
            "alias_ids": alias_ids,
            "view_content_hash": view_hashes,
            "metric": df["metric"],
            "value": df["value"],
        }
    )
    enriched["k"] = enriched["k"].astype(int)
    order = ["backbone", "k", "strategy_key", "metric"]
    return enriched.sort_values(order, kind="mergesort").reset_index(drop=True)


def query_medoid_baselines(
    con,
    *,
    run_id: str | None = None,
) -> pd.DataFrame:
    """Load the observed global-medoid baseline ``analyze_metrics`` rows as a decoded frame.

    Distinct from :func:`query_analyze_metrics` (catalog-only, pinned forever): reads every
    ``analyze_metrics`` row with ``strategy_type == MEDOID_STRATEGY_TYPE`` (``"global_pool"``,
    the observed ``global_pool:{backbone}:medoid`` baseline persisted by the analyze phase),
    optionally restricted to *run_id*.  Each row is one literal
    ``(strategy_key, sim_metric, k, metric, value)`` cell of that baseline identity; backbone is
    parsed from the strategy key.  A medoid baseline is NOT a catalog class — it has no config
    identity or provenance scope, so ``score_variant`` / ``scoring_semantics_version`` /
    ``representation_hash`` / ``canonical_config_id`` / ``alias_ids`` / ``view_content_hash``
    are ``None``/empty.  Rows whose key is not a well-formed ``global_pool:{bb}:medoid`` key are
    dropped (a data-integrity anomaly, never a strategy-filter).  Returns an empty
    :data:`CATALOG_ANALYSIS_COLUMNS` frame when the table is absent or has no medoid rows.
    """
    columns = list(CATALOG_ANALYSIS_COLUMNS)
    if not table_exists(con, "analyze_metrics"):
        return empty_df(columns)

    params: list[object] = [MEDOID_STRATEGY_TYPE]
    where_run = ""
    if run_id is not None:
        where_run = " AND run_id = ?"
        params.append(run_id)
    try:
        df = con.execute(
            "SELECT run_id, strategy_key, sim_metric, k, metric, value "
            "FROM analyze_metrics WHERE strategy_type = ?" + where_run,
            params,
        ).df()
    except Exception:
        return empty_df(columns)

    if df.empty:
        return empty_df(columns)

    backbones: list[Any] = []
    valid = []
    for sk in df["strategy_key"]:
        parts = str(sk).split(":")
        if len(parts) == 3 and parts[0] == "global_pool" and bool(parts[1]) and parts[2] == "medoid":
            backbones.append(parts[1])
            valid.append(True)
        else:
            backbones.append(None)
            valid.append(False)
    keep = [i for i, ok in enumerate(valid) if ok]
    if not keep:
        return empty_df(columns)
    df = df.iloc[keep].reset_index(drop=True)
    backbone_col = [backbones[i] for i in keep]

    enriched = pd.DataFrame(
        {
            "run_id": df["run_id"],
            "backbone": backbone_col,
            "strategy_key": df["strategy_key"],
            "strategy_type": MEDOID_STRATEGY_TYPE,
            "sim_metric": df["sim_metric"],
            "k": df["k"].astype(int),
            "score_variant": [None] * len(df),
            "scoring_semantics_version": [None] * len(df),
            "representation_hash": [None] * len(df),
            "canonical_config_id": [None] * len(df),
            "alias_ids": [[] for _ in range(len(df))],
            "view_content_hash": [None] * len(df),
            "metric": df["metric"],
            "value": df["value"],
        }
    )
    order = ["backbone", "k", "strategy_key", "metric"]
    return enriched.sort_values(order, kind="mergesort").reset_index(drop=True)


def query_winners_metrics(
    con,
    *,
    run_id: str | None = None,
) -> pd.DataFrame:
    """The decoded winners/summary frame: catalog classes PLUS observed medoid baselines.

    Concatenation of :func:`query_analyze_metrics` (catalog classes) and
    :func:`query_medoid_baselines` (per-backbone observed ``global_pool:{backbone}:medoid``
    baselines), both run-scoped identically.  This enriched frame carries each cell's medoid
    baseline row so :func:`build_winner_delta_rows` (and the summary / winners sections) can
    delegate baseline/winner/delta selection to the observed medoid.  ``section_analysis`` must
    keep using the catalog-only :func:`query_analyze_metrics` frame (never this one), so the
    catalog-only pin in ``tests/test_report.py`` stays valid.
    """
    catalog = query_analyze_metrics(con, run_id=run_id)
    medoid = query_medoid_baselines(con, run_id=run_id)
    if medoid.empty:
        return catalog
    if catalog.empty:
        return medoid
    return pd.concat([catalog, medoid], ignore_index=True)


# ---------------------------------------------------------------------------
# Analysis section renderer
# ---------------------------------------------------------------------------


def _class_table_rows(bb_df: pd.DataFrame) -> list[dict]:
    """One analysis row per (strategy_key, k, metric) cell for a backbone, alias-joined."""
    rows: list[dict] = []
    for _, r in bb_df.iterrows():
        rows.append(
            {
                "run_id": fmt(r.get("run_id")) if pd.notna(r.get("run_id")) else "—",
                "strategy_key": r["strategy_key"],
                "sim_metric": r["sim_metric"],
                "k": int(r["k"]),
                "metric": r["metric"],
                "value": float(r["value"]),
                "score_variant": r["score_variant"],
                "scoring_semantics_version": int(r["scoring_semantics_version"]),
                "canonical_config_id": fmt(r.get("canonical_config_id")),
                "alias_ids": _alias_text(r.get("alias_ids")),
                "representation_hash": r["representation_hash"],
                "view_content_hash": fmt(r.get("view_content_hash")),
            }
        )
    return rows


def _alias_text(alias_ids) -> str:
    if not alias_ids:
        return "—"
    return ",".join(str(a) for a in alias_ids)


def section_analysis(df: pd.DataFrame) -> dict:
    """Render the active catalog ``analyze_metrics`` rows into the ``analysis`` section.

    One per-backbone subsection, each with a table of decoded catalog rows.  Equal search
    representations were collapsed to one class by the analyze pipeline, so each
    ``strategy_key`` appears once per (sim_metric, k, metric) cell with its sorted alias list
    carried alongside — aliases never create duplicate metric/score rows.
    """
    if df is None or df.empty or "backbone" not in df.columns:
        return make_section(
            "analysis",
            "Catalog Analysis",
            empty_message="No active catalog analysis results. Run the analyze phase.",
        )

    subsections: list[dict] = []
    for backbone in sorted({str(b) for b in df["backbone"].dropna().tolist()}):
        bb_df = df[df["backbone"] == backbone]
        table_rows = _class_table_rows(bb_df)
        if not table_rows:
            continue
        subsections.append(
            {
                "id": f"analysis-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [],
                "charts": [],
                "tables": [
                    make_table(
                        table_rows,
                        id=f"catalog_analysis_{backbone}",
                        title=f"Active catalog analysis rows ({backbone})",
                        collapsible=True,
                        summary_text=f"{len(table_rows)} active catalog row(s)",
                    )
                ],
                "panels": [],
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    if not subsections:
        return make_section(
            "analysis",
            "Catalog Analysis",
            empty_message="No active catalog analysis results. Run the analyze phase.",
        )

    return make_section(
        "analysis",
        "Catalog Analysis",
        description=(
            "Active catalog-only analyze_metrics rows: one row per (strategy_key, sim_metric, "
            "k, metric).  Each strategy_key is a collapsed search-representation class "
            "(equal representations scored once); its sorted alias config ids and the "
            "view-content/representation hash provenance are carried on every row.  EffNet and "
            "MusicNN are independent per-backbone populations and are never cross-averaged."
        ),
        subsections=subsections,
    )
