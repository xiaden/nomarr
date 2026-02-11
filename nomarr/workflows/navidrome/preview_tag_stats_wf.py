"""Preview tag statistics workflow.

This workflow computes statistics for all tags in the library, useful for
debugging and understanding tag data before generating Navidrome config.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.navidrome.tag_query_comp import (
    get_tag_value_counts,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

def preview_tag_stats_workflow(db: Database, namespace: str="nom") -> dict[str, dict[str, Any]]:
    """Preview statistics for all tags in the library.

    Returns stats for all tags: both standard tags (artist, album, year, etc.)
    and nomarr-namespaced tags (nom:mood-*, nom:effnet_*, etc.).

    Args:
        db: Database instance
        namespace: Tag namespace (default: "nom") — currently unused, kept for API compat

    Returns:
        Dict of tag_key -> stats dict (type, is_multivalue, summary, count)

    """
    all_rels = db.tags.get_unique_rels(nomarr_only=False)
    logger.info(f"[navidrome] Computing summaries for {len(all_rels)} tag types...")
    stats_by_tag: dict[str, dict[str, Any]] = {}
    for idx, rel in enumerate(all_rels, 1):
        try:
            if idx % 10 == 0:
                logger.info(f"[navidrome] Progress: {idx}/{len(all_rels)} tags processed...")
            value_counts = get_tag_value_counts(db, rel)
            total_count = sum(value_counts.values())
            if value_counts:
                # Separate numeric and non-numeric values for type detection
                numeric_values = [v for v in value_counts if isinstance(v, (int, float))]
                if numeric_values and len(numeric_values) > len(value_counts) / 2:
                    # Majority numeric — treat as numeric tag
                    first_numeric = numeric_values[0]
                    tag_type = "float" if isinstance(first_numeric, float) else "integer"
                else:
                    tag_type = "string"
            else:
                tag_type = "unknown"
            if tag_type in ("float", "integer"):
                # Use only numeric values for min/max to avoid type comparison errors
                numeric_vals = [v for v in value_counts if isinstance(v, (int, float))]
                if numeric_vals:
                    summary = f"min={min(numeric_vals)}, max={max(numeric_vals)}, unique={len(numeric_vals)}"
                else:
                    summary = "no values"
            else:
                summary = f"unique={len(value_counts)}"
            stats_by_tag[rel] = {"type": tag_type, "is_multivalue": len(value_counts) > 1, "summary": summary, "total_count": total_count}
        except Exception as e:
            logger.exception(f"[navidrome] Error computing summary for {rel}: {e}")
            stats_by_tag[rel] = {"type": "string", "is_multivalue": False, "summary": f"Error: {e!s}", "total_count": 0}
    logger.info(f"[navidrome] Completed {len(stats_by_tag)} tag summaries")
    return stats_by_tag
