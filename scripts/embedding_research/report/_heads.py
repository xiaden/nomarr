"""Head analysis sections: correlation heatmaps and CTP/PTC value."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as _np
import plotly.graph_objects as go

from scripts.embedding_research.db.head_phase import load_head_phase_provenance
from scripts.embedding_research.head_pooling import (
    BOUNDARY_SOURCE_EFFNET_PTC,
    HEAD_POOL_VARIANT,
)

from ._base import (
    _FONT_COLOR,
    _H_SMALL,
    apply_dark_theme,
    binned_config_label,
    fmt,
    make_chart,
    make_section,
    make_table,
    table_exists,
)

if TYPE_CHECKING:
    import pandas as pd

_PALETTE = [
    "#7aa2f7",
    "#9ece6a",
    "#f7768e",
    "#e0af68",
    "#bb9af7",
    "#7dcfff",
    "#ff9e64",
    "#73daca",
    "#c0caf5",
    "#b4f9f8",
    "#cba6f7",
    "#fab387",
    "#a6e3a1",
    "#f38ba8",
    "#89b4fa",
]

try:
    from scripts.embedding_research.helpers.binning import BIN_MODES, DIST_THRESHOLDS

    _THRESH_SQL = ", ".join(str(t) for t in DIST_THRESHOLDS) if DIST_THRESHOLDS else "1.0"
    _BIN_MODE_SQL = ", ".join(f"'{m}'" for m in BIN_MODES) if BIN_MODES else "'temporal_global'"
except ImportError:
    _THRESH_SQL = "1.0"
    _BIN_MODE_SQL = "'temporal_global'"


def section_head_sim_corr(con) -> dict:
    """Spearman rank correlation between head attention and embedding similarity."""
    if not table_exists(con, "head_sim_corr_rows"):
        return make_section(
            "head-sim-corr",
            "Head \u00d7 Embedding Similarity Correlation",
            empty_message=("Run the classify and analyze phases to populate this section."),
        )

    try:
        df = con.execute(
            "SELECT backbone, head, bin_mode, std_thresh, rep_a, rep_b, agg_method, "
            "ROUND(corr, 4) AS spearman_r "
            "FROM head_sim_corr_rows ORDER BY backbone, head, bin_mode, std_thresh"
        ).df()
    except Exception as exc:
        return make_section(
            "head-sim-corr",
            "Head \u00d7 Embedding Similarity Correlation",
            empty_message=f"Query error: {exc}",
        )

    if df.empty:
        return make_section(
            "head-sim-corr",
            "Head \u00d7 Embedding Similarity Correlation",
            empty_message="No correlation data yet.",
        )

    df["strategy"] = df.apply(
        lambda r: binned_config_label(
            bin_mode=r["bin_mode"],
            std_thresh=r["std_thresh"],
            rep_a=r["rep_a"],
            rep_b=r["rep_b"],
            agg_method=r["agg_method"],
        ),
        axis=1,
    )

    all_backbones = sorted(df["backbone"].unique())
    subsections: list[dict] = []

    for backbone in all_backbones:
        bb_df = df[df["backbone"] == backbone]
        all_heads = sorted(bb_df["head"].unique())
        all_strats = sorted(bb_df["strategy"].unique())

        pivot = bb_df.pivot_table(index="head", columns="strategy", values="spearman_r", aggfunc="mean").reindex(
            index=all_heads, columns=all_strats
        )

        data = pivot.values.astype(float)
        text = [[f"{v:.3f}" if not _np.isnan(v) else "" for v in row] for row in data]
        height = max(_H_SMALL, len(all_heads) * 40 + 100)

        max_abs = float(_np.nanmax(_np.abs(data))) if not _np.all(_np.isnan(data)) else 0.5
        max_abs = max(max_abs, 0.01)

        fig = go.Figure(
            go.Heatmap(
                z=data.tolist(),
                x=all_strats,
                y=all_heads,
                text=text,
                texttemplate="%{text}",
                textfont={"size": 9},
                colorscale="RdYlGn",
                zmid=0,
                zmin=-max_abs,
                zmax=max_abs,
                colorbar={"title": "Spearman r", "tickfont": {"color": "#aaa", "size": 9}},
            )
        )
        apply_dark_theme(fig, grid=False)
        fig.update_layout(
            title={"text": f"{backbone} \u2014 head\u00d7strategy Spearman r", "font": {"color": _FONT_COLOR}},
            height=height,
            xaxis={"tickfont": {"color": _FONT_COLOR, "size": 9}},
            yaxis={"tickfont": {"color": _FONT_COLOR, "size": 9}},
        )

        # Best config per head table
        best_rows = (
            bb_df.sort_values("spearman_r", ascending=False)
            .groupby("head", as_index=False)
            .first()[["head", "strategy", "spearman_r"]]
            .rename(columns={"strategy": "best strategy", "spearman_r": "best r"})
            .to_dict("records")
        )

        subsections.append(
            {
                "id": f"corr-{backbone}",
                "title": str(backbone),
                "description": "",
                "stats": [],
                "charts": [make_chart(fig, id=f"corr_{backbone}", title=f"{backbone} head\u00d7strategy Spearman r")],
                "tables": [
                    make_table(
                        best_rows, id=f"corr_best_{backbone}", collapsible=True, summary_text="Best strategy per head"
                    )
                ],
                "panels": [],
                "subsections": [],
                "warnings": [],
                "headline": None,
                "empty_message": "",
            }
        )

    return make_section(
        "head-sim-corr",
        "Head \u00d7 Embedding Similarity Correlation",
        description=(
            "Spearman rank correlation between head attention weights and embedding cosine similarity "
            "per song pair, aggregated per (backbone, head, strategy). "
            "Positive r = head attends to similar embeddings; negative r = head ignores similarity."
        ),
        subsections=subsections,
    )


def section_head_value(con, flat_df: pd.DataFrame | None = None) -> dict:  # noqa: ARG001 - flat_df kept for backward-compatible call signature (archival CTP note no longer uses it)
    """ARCHIVAL CTP reference (deferred). Never a primary winner/delta surface.

    CTP (classify-then-pool) is a deferred, archival pathway that is excluded from
    the primary EffNet PTC-versus-global-medoid experiment.  This section is
    retained purely as a labelled archival note and raw reference table; exact
    primary winners/deltas live in the 'Exact Winners & Deltas' section and shared
    head-output preparation lives in the 'head-output-shared-ptc-boundary' section.
    """
    archival_warning = {
        "message": (
            "ARCHIVAL / DEFERRED: CTP is not part of the primary experiment. This "
            "section is reference-only and never contributes primary winner/delta rows."
        )
    }
    has_ptc_ctp = table_exists(con, "ptc_ctp_rows")
    if not has_ptc_ctp:
        return make_section(
            "head-value",
            "Head Value (Archival CTP Reference)",
            warnings=[archival_warning],
            empty_message=(
                "No archival CTP comparison rows (ptc_ctp_rows) present. CTP is "
                "deferred/archival and excluded from primary analysis."
            ),
        )
    try:
        df = con.execute(
            "SELECT backbone, head, strategy, "
            "ROUND(ptc_disc, 4) AS ptc_disc, ROUND(ctp_disc, 4) AS ctp_disc, "
            "ROUND(delta_disc, 4) AS delta_disc "
            "FROM ptc_ctp_rows ORDER BY backbone, head, strategy"
        ).df()
    except Exception as exc:
        return make_section(
            "head-value",
            "Head Value (Archival CTP Reference)",
            warnings=[archival_warning],
            empty_message=f"Query error: {exc}",
        )
    if df.empty:
        return make_section(
            "head-value",
            "Head Value (Archival CTP Reference)",
            warnings=[archival_warning],
            empty_message="No archival CTP comparison data.",
        )
    return make_section(
        "head-value",
        "Head Value (Archival CTP Reference)",
        description=(
            "ARCHIVAL / DEFERRED. CTP (classify-then-pool) is a deferred, archival "
            "pathway that is excluded from the primary EffNet PTC-versus-global-medoid "
            "experiment. This section is retained for reference only and is never a "
            "primary winner or delta source; exact primary winners/deltas live in the "
            "'Exact Winners & Deltas' section, and shared-boundary head-output "
            "preparation lives in the 'head-output-shared-ptc-boundary' section. The "
            "table below shows the raw archival ptc_ctp_rows comparison rows (Δdisc = "
            "ctp_disc - ptc_disc) as reference data only."
        ),
        warnings=[archival_warning],
        tables=[
            make_table(
                df.to_dict("records"),
                id="head_value_archival_ctp",
                title="Archival CTP reference rows",
            )
        ],
    )


def section_head_output_shared_ptc_boundary(con, manifest=None) -> dict:
    """Shared EffNet PTC boundary head-output preparation status and coverage.

    Describes whether the shared ``effnet_ptc`` boundary head phase has been prepared
    for each (head, bin_mode, threshold) configuration, the persisted shared-boundary
    provenance (``boundary_source="effnet_ptc"``, ``head_pool_variant=...``),
    per-threshold song coverage (``n_songs`` / ``n_pooled``), and any missing-data
    warnings.  This is a preparation-status section only and never emits primary
    winner/delta rows.
    """
    warnings: list[dict] = []
    if manifest is not None:
        if manifest.errors:
            warnings.append(
                {
                    "message": (
                        f"Head phase finished with {manifest.errors} error configuration(s); shared-boundary "
                        "head outputs are incomplete."
                    )
                }
            )
        if manifest.done == 0 and sum(r.n_pooled for r in manifest.results) == 0:
            warnings.append(
                {
                    "message": (
                        f"Head phase produced no pooled output (skipped={manifest.skipped} errors={manifest.errors}); "
                        "shared-boundary head outputs are unavailable in this report."
                    )
                }
            )

    has_tbl = table_exists(con, "head_phase_provenance")
    rows = load_head_phase_provenance(con) if has_tbl else []

    if not rows and manifest is None:
        warnings.append(
            {
                "message": (
                    "No shared-boundary head-phase provenance found. Run the head phase "
                    "(classify.run_shared_ptc_head_pooling) to populate head-output provenance."
                )
            }
        )

    if not rows:
        return make_section(
            "head-output-shared-ptc-boundary",
            "Head Output: Shared PTC Boundary",
            description=(
                "Preparation status and per-threshold coverage for the shared EffNet PTC "
                'boundary head phase (boundary_source="effnet_ptc"). This is a '
                "preparation-status section only and never emits primary winner/delta rows."
            ),
            warnings=warnings,
            empty_message=("No shared-boundary head-phase data yet. Run the head phase to populate provenance."),
        )

    status_counts: dict[str, int] = {}
    for r in rows:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
    status_desc = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items())) or "none"

    table_rows: list[dict] = []
    for r in rows:
        cov = ""
        if r.n_songs > 0:
            cov = f"{100.0 * r.n_pooled / r.n_songs:.1f}%"
        table_rows.append(
            {
                "head": r.head,
                "bin_mode": r.bin_mode,
                "threshold": fmt(r.threshold),
                "status": r.status,
                "n_songs": str(r.n_songs),
                "n_pooled": str(r.n_pooled),
                "coverage": cov,
                "boundary_source": r.boundary_source,
                "head_pool_variant": r.head_pool_variant,
                "reference_corpus_hash": (r.reference_corpus_hash or "—"),
            }
        )

    return make_section(
        "head-output-shared-ptc-boundary",
        "Head Output: Shared PTC Boundary",
        description=(
            "Shared-boundary head-phase preparation status and per-threshold coverage. "
            f'boundary_source = "{BOUNDARY_SOURCE_EFFNET_PTC}" and head_pool_variant = '
            f'"{HEAD_POOL_VARIANT}" prove the shared EffNet PTC boundary provenance; '
            "n_pooled/n_songs is the fraction of songs with pooled head output at each "
            "(head, bin_mode, threshold). This section is preparation metadata only and "
            "never emits primary winner/delta rows."
        ),
        warnings=warnings,
        tables=[
            make_table(
                table_rows,
                id="head_phase_provenance",
                title=f"Head-phase provenance (status: {status_desc})",
            )
        ],
    )
