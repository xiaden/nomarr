"""Optimizer results section."""

from __future__ import annotations

import pathlib

import pandas as pd

from ._base import fmt, make_panel, make_section, make_table

# Root that contains the optimizer/ sub-directory.
OUTPUT_ROOT = pathlib.Path(__file__).parents[1] / "outputs"


def load_optimizer_curves() -> list[dict]:
    """Load all optimizer threshold-curve CSVs from the outputs/optimizer directory.

    Returns a list of dicts::

        {
            "backbone": str,
            "bin_mode": str,
            "data": pd.DataFrame,  # full curve, sorted by objective_total desc
            "best": dict,  # row with highest objective_total
            "source": pathlib.Path,
        }
    """
    opt_dir = OUTPUT_ROOT / "optimizer"
    if not opt_dir.exists():
        return []

    curves: list[dict] = []
    for csv_path in sorted(opt_dir.glob("*.csv")):
        try:
            df = pd.read_csv(csv_path)
            if df.empty:
                continue
            obj_col = next((c for c in ("objective_total", "objective") if c in df.columns), None)
            if obj_col is None:
                continue
            df = df.sort_values(obj_col, ascending=False).reset_index(drop=True)
            best_row = df.iloc[0].to_dict()
            # Derive backbone / bin_mode from filename  e.g.  backbone__bin_mode.csv
            stem = csv_path.stem
            if "__" in stem:
                bb, bm = stem.split("__", 1)
            else:
                bb, bm = stem, "unknown"
            curves.append(
                {
                    "backbone": bb,
                    "bin_mode": bm,
                    "data": df,
                    "best": best_row,
                    "source": csv_path,
                }
            )
        except Exception:
            continue

    return curves


def section_optimizer() -> dict:
    """Optimizer results: per backbone/bin_mode best threshold and top-3 candidates."""
    opt_dir = OUTPUT_ROOT / "optimizer"
    if not opt_dir.exists():
        return make_section(
            "optimizer",
            "Optimizer Results",
            empty_message="No optimizer artifacts found. Run the optimize phase first.",
        )

    curves = load_optimizer_curves()
    if not curves:
        return make_section(
            "optimizer",
            "Optimizer Results",
            empty_message="No threshold-curve CSVs found. Run the optimize phase first.",
        )

    summary_rows: list[dict] = []
    panels: list[dict] = []

    for curve in curves:
        backbone = str(curve["backbone"])
        bin_mode = str(curve["bin_mode"])
        df: pd.DataFrame = curve["data"]
        best: dict = curve["best"]

        top3_rows = []
        for _, row in df.head(3).iterrows():
            top3_rows.append(
                {
                    "threshold": row.get("threshold_key", row.get("threshold", "\u2014")),
                    "objective": fmt(row.get("objective_total")),
                    "disc_general": fmt(row.get("disc_general")),
                    "disc_artist": fmt(row.get("disc_artist")),
                    "disc_genre": fmt(row.get("disc_genre")),
                    "disc_head": fmt(row.get("disc_head")),
                    "map_k": fmt(row.get("map_k")),
                    "mrr": fmt(row.get("mrr")),
                    "ndcg_k": fmt(row.get("ndcg_k")),
                    "recall_k": fmt(row.get("recall_k")),
                    "layout\u0394": fmt(row.get("layout_changed_count_vs_prev")),
                }
            )

        best_threshold = best.get("threshold_key", best.get("threshold", "\u2014"))
        obj_val = fmt(best.get("objective_total"))
        summary_rows.append(
            {
                "backbone": backbone,
                "bin_mode": bin_mode,
                "best threshold": str(best_threshold),
                "best objective": obj_val,
                "median bins": fmt(best.get("median_bins_per_song")),
                "disc_general": fmt(best.get("disc_general")),
                "map_k": fmt(best.get("map_k")),
                "n evals": str(len(df)),
                "source": curve["source"].name,
            }
        )

        panels.append(
            make_panel(
                id=f"optimizer_{backbone}_{bin_mode}",
                title=f"{backbone} / {bin_mode} \u2014 best t={best_threshold} (objective={obj_val})",
                tables=[
                    make_table(
                        top3_rows,
                        id=f"top3_{backbone}_{bin_mode}",
                        title="Top 3 candidates",
                    )
                ],
            )
        )

    if not summary_rows:
        return make_section(
            "optimizer",
            "Optimizer Results",
            empty_message="Optimizer artifacts found, but no readable threshold-curve data was parsed.",
        )

    summary_rows = sorted(summary_rows, key=lambda r: (r["backbone"], r["bin_mode"]))

    return make_section(
        "optimizer",
        "Optimizer Results",
        description=(
            f"Threshold optimization outputs from {opt_dir.as_posix()}. "
            "The table shows the selected threshold per backbone/bin mode (max objective), "
            "with top-3 candidate rows expanded in the panels below."
        ),
        tables=[make_table(summary_rows, id="optimizer_summary", title="Optimizer summary")],
        panels=panels,
    )
