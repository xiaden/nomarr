"""Preview tag statistics workflow.

This workflow computes statistics for all tags in the library, useful for
debugging and understanding tag data before generating Navidrome config.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.navidrome.tag_query_comp import (
    get_nomarr_tag_rels,
    get_tag_value_counts,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

def preview_tag_stats_workflow(db: Database, namespace: str="nom") -> dict[str, dict[str, Any]]:
    """Preview statistics for all tags in the library.

    Useful for debugging and understanding your tag data before generating config.

    Args:
        db: Database instance
        namespace: Tag namespace (default: "nom")

    Returns:
        Dict of tag_key -> stats dict (type, is_multivalue, summary, count)

    """
    all_rels = get_nomarr_tag_rels(db)
    f"nom:{namespace}:" if not namespace.startswith("nom:") else f"{namespace}:"
    filtered_rels = [rel for rel in all_rels if rel.startswith("nom:")]
    logger.info(f"[navidrome] Computing summaries for {len(filtered_rels)} tag types...")
    stats_by_tag = {}
    for idx, rel in enumerate(filtered_rels, 1):
        try:
            if idx % 10 == 0:
                logger.info(f"[navidrome] Progress: {idx}/{len(filtered_rels)} tags processed...")
            value_counts = get_tag_value_counts(db, rel)
            total_count = sum(value_counts.values())
            if value_counts:
                first_value = next(iter(value_counts.keys()))
                if isinstance(first_value, float):
                    tag_type = "float"
                elif isinstance(first_value, int):
                    tag_type = "integer"
                else:
                    tag_type = "string"
            else:
                tag_type = "unknown"
            if tag_type in ("float", "integer"):
                values = list(value_counts.keys())
                summary = f"min={min(values)}, max={max(values)}, unique={len(values)}" if values else "no values"
            else:
                summary = f"unique={len(value_counts)}"
            stats_by_tag[rel] = {"type": tag_type, "is_multivalue": len(value_counts) > 1, "summary": summary, "total_count": total_count}
        except Exception as e:
            logger.exception(f"[navidrome] Error computing summary for {rel}: {e}")
            stats_by_tag[rel] = {"type": "string", "is_multivalue": False, "summary": f"Error: {e!s}", "total_count": 0}
    logger.info(f"[navidrome] Completed {len(stats_by_tag)} tag summaries")
    return stats_by_tag
