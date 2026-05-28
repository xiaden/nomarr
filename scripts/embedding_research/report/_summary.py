"""Top-line summary section: disc_genre dominance rate per backbone."""

from __future__ import annotations

import pandas as pd

from ._base import binned_config_label, fmt, make_section, make_table

_BINNED_CONFIG_COLS = ["bin_mode", "std_thresh", "rep_a", "rep_b", "agg_method"]


def _dominance_rate(
    binned_df: pd.DataFrame,
    flat_df: pd.DataFrame,
    backbone: str,
    col: str = "disc_genre",
) -> tuple[float, float, float]:
    flat_sub = flat_df[flat_df["backbone"] == backbone] if "backbone" in flat_df.columns else pd.DataFrame()
    binned_raw = binned_df[binned_df["backbone"] == backbone] if "backbone" in binned_df.columns else pd.DataFrame()
    if binned_raw.empty or any(cfg_col not in binned_raw.columns for cfg_col in _BINNED_CONFIG_COLS):
        return (0.0, 0.0, 0.0)

    binned_sub = binned_raw.groupby(_BINNED_CONFIG_COLS, dropna=False).first().reset_index()

    if flat_sub.empty or binned_sub.empty or col not in flat_sub.columns or col not in binned_sub.columns:
        return (0.0, 0.0, 0.0)

    flat_scores = flat_sub[col].dropna()
    binned_scores = binned_sub[col].dropna()
    if flat_scores.empty or binned_scores.empty:
        return (0.0, 0.0, 0.0)

    flat_best = float(flat_scores.max()) if not flat_scores.empty else 0.0
    dominance_rate = float((binned_scores > flat_best).mean())
    return (dominance_rate, flat_best, float(binned_scores.max()))


def section_summary(df: pd.DataFrame) -> dict:
    """Compare flat vs binned retrieval by disc_genre dominance rate per backbone."""
    flat_df = df[df["strategy_type"] == "global_pool"]
    binned_df = df[df["strategy_type"].isin(["ptc", "ctp"])]
    flat_backbones = flat_df["backbone"].dropna().unique().tolist() if "backbone" in flat_df.columns else []
    binned_backbones = binned_df["backbone"].dropna().unique().tolist() if "backbone" in binned_df.columns else []
    all_backbones = sorted(set(flat_backbones) | set(binned_backbones))

    if not all_backbones:
        return make_section(
            "summary",
            "Summary",
            empty_message="No retrieval data yet. Run the eval phase first.",
        )

    rows: list[dict] = []
    section_warnings: list[dict] = []
    verdicts: list[str] = []

    for backbone in all_backbones:
        flat_sub = flat_df[flat_df["backbone"] == backbone] if "backbone" in flat_df.columns else pd.DataFrame()
        binned_raw = binned_df[binned_df["backbone"] == backbone] if "backbone" in binned_df.columns else pd.DataFrame()
        binned_sub = (
            binned_raw.groupby(_BINNED_CONFIG_COLS, dropna=False).first().reset_index()
            if not binned_raw.empty and all(col in binned_raw.columns for col in _BINNED_CONFIG_COLS)
            else pd.DataFrame()
        )

        if "n_songs" in flat_sub.columns and "n_songs" in binned_raw.columns:
            flat_counts = sorted({int(v) for v in flat_sub["n_songs"].dropna().tolist()})
            binned_counts = sorted({int(v) for v in binned_raw["n_songs"].dropna().tolist()})
            if flat_counts and binned_counts and flat_counts != binned_counts:
                section_warnings.append(
                    {
                        "id": f"n_songs_mismatch_{backbone}",
                        "level": "warning",
                        "message": f"Corpus size mismatch for {backbone}",
                        "detail": (
                            f"Flat rows report n_songs={flat_counts} while binned rows report "
                            f"n_songs={binned_counts}. Compare scores cautiously until the corpus "
                            "inputs are aligned."
                        ),
                    }
                )

        dominance_rate, flat_best_disc_genre, binned_best_disc_genre = _dominance_rate(
            binned_df,
            flat_df,
            backbone,
        )

        flat_composite_tuning_sens = None
        if "disc_genre" in flat_sub.columns:
            flat_scores = flat_sub["disc_genre"].dropna()
            if not flat_scores.empty:
                flat_iqr = float(flat_scores.quantile(0.75) - flat_scores.quantile(0.25))
                flat_composite_tuning_sens = float(flat_scores.median() - 0.5 * flat_iqr)

        binned_composite_tuning_sens = None
        if not binned_sub.empty and "disc_genre" in binned_sub.columns:
            binned_scores = binned_sub["disc_genre"].dropna()
            if not binned_scores.empty:
                binned_iqr = float(binned_scores.quantile(0.75) - binned_scores.quantile(0.25))
                binned_composite_tuning_sens = float(binned_scores.median() - 0.5 * binned_iqr)

        best_binned_config = "—"
        if not binned_sub.empty and "disc_genre" in binned_sub.columns and binned_sub["disc_genre"].notna().any():
            best_idx = binned_sub["disc_genre"].idxmax()
            best_row = binned_sub.loc[best_idx]
            best_binned_config = binned_config_label(
                bin_mode=best_row.get("bin_mode"),
                std_thresh=best_row.get("std_thresh"),
                rep_a=best_row.get("rep_a"),
                rep_b=best_row.get("rep_b"),
                agg_method=best_row.get("agg_method"),
            )

        if dominance_rate > 0.66:
            verdict = "consistently better"
        elif dominance_rate > 0.33:
            verdict = "sometimes better"
        else:
            verdict = "not better"
        verdicts.append(verdict)

        rows.append(
            {
                "backbone": backbone,
                "dominance_rate": f"{dominance_rate * 100:.1f}%",
                "verdict": verdict,
                "flat_best_disc_genre": fmt(flat_best_disc_genre),
                "binned_best_disc_genre": fmt(binned_best_disc_genre),
                "flat_composite_tuning_sens": fmt(flat_composite_tuning_sens),
                "binned_composite_tuning_sens": fmt(binned_composite_tuning_sens),
                "best_binned_config": best_binned_config,
            }
        )

    if any(verdict == "consistently better" for verdict in verdicts):
        headline = {
            "color": "#22c55e",
            "icon": "✓",
            "text": (
                "At least one backbone is consistently better: more than 66% of unique binned "
                "configs beat flat on disc_genre."
            ),
        }
    elif any(verdict == "sometimes better" for verdict in verdicts):
        headline = {
            "color": "#f59e0b",
            "icon": "⚠",
            "text": (
                "Binning is sometimes better: at least one backbone has 33%-66% of unique binned "
                "configs beating flat on disc_genre."
            ),
        }
    else:
        headline = {
            "color": "#f87171",
            "icon": "✕",
            "text": (
                "Binning is not better here: all backbones have 33% or fewer unique binned configs "
                "beating flat on disc_genre."
            ),
        }

    return make_section(
        "summary",
        "Summary",
        description=(
            "Per-backbone verdicts are based on disc_genre dominance rate: the fraction of unique "
            "binned configs that beat the best flat result. Tuning-sensitivity composites "
            "(median - 0.5xIQR) are shown as context only."
        ),
        stats=[],
        charts=[],
        tables=[make_table(rows, id="backbone_summary", title="Backbone summary")],
        panels=[],
        subsections=[],
        warnings=section_warnings,
        headline=headline,
        empty_message="",
    )
