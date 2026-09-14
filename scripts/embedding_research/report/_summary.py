"""Geometry analysis summary section (normalized run-scoped evidence)."""

from __future__ import annotations

from typing import Any


def _class_counts(result: Any) -> list[dict]:
    counts: dict[str, int] = {}
    for row in result.class_aggregate_metrics:
        counts[row.corpus_search_class_id] = counts.get(row.corpus_search_class_id, 0) + 1
    return [
        {"corpus_search_class_id": str(class_id), "metric_cells": count, "finite_cells": count}
        for class_id, count in sorted(counts.items())
    ]


def _backbone_counts(result: Any) -> list[dict]:
    counts: dict[str, int] = {}
    for row in result.baseline_aggregate_metrics:
        counts[row.backbone] = counts.get(row.backbone, 0) + 1
    return [
        {"backbone": str(backbone), "metric_cells": count, "finite_cells": count}
        for backbone, count in sorted(counts.items())
    ]


def section_summary(result: Any = None) -> dict:
    """Summarize the single threshold-independent baseline and class-scoped metric coverage."""
    from ._base import make_section, make_table

    has_analysis = result is not None and bool(result.class_aggregate_metrics)
    has_baseline = result is not None and bool(result.baseline_aggregate_metrics)
    if not has_analysis and not has_baseline:
        return make_section(
            "summary",
            "Geometry Result Status",
            warnings=[{"level": "error", "message": "No exact geometry analysis evidence; summary refused."}],
            empty_message="REFUSED: no exact geometry analysis or observed-baseline evidence.",
        )

    stats: list[dict] = []
    tables: list[dict] = []
    if has_analysis:
        stats.extend(
            [
                {"label": "class metric rows", "value": len(result.class_aggregate_metrics)},
                {
                    "label": "classes",
                    "value": len({row.corpus_search_class_id for row in result.class_aggregate_metrics}),
                },
                {
                    "label": "metrics",
                    "value": len({row.metric for row in result.class_aggregate_metrics}),
                },
            ]
        )
        tables.append(
            make_table(
                _class_counts(result),
                id="geometry_threshold_summary",
                title="Class-scoped metric coverage summary",
            )
        )
    if has_baseline:
        stats.append({"label": "baseline rows", "value": len(result.baseline_aggregate_metrics)})
        tables.append(
            make_table(
                _backbone_counts(result),
                id="observed_baseline_summary",
                title="Observed global-medoid baseline summary",
            )
        )

    return make_section(
        "summary",
        "Geometry Result Status",
        description=(
            "Exact run-scoped geometry evidence only. Class-scoped threshold metrics and the "
            "single threshold-independent observed global-medoid baseline are counted separately."
        ),
        stats=stats,
        tables=tables,
    )
