"""
Preview tag statistics workflow.

This workflow computes statistics for all tags in the library, useful for
debugging and understanding tag data before generating Navidrome config.
"""

import logging
from typing import Any

from nomarr.persistence.db import Database


def preview_tag_stats_workflow(db: Database, namespace: str = "nom") -> dict[str, dict[str, Any]]:
    """
    Preview statistics for all tags in the library.

    Useful for debugging and understanding your tag data before generating config.

    Args:
        db: Database instance
        namespace: Tag namespace (default: "nom")

    Returns:
        Dict of tag_key -> stats dict (type, is_multivalue, summary, count)
    """
    # Get unique rels for nomarr tags
    all_rels = db.tags.get_unique_rels(nomarr_only=True)
    f"nom:{namespace}:" if not namespace.startswith("nom:") else f"{namespace}:"
    # Also match simple "nom:" prefix
    filtered_rels = [rel for rel in all_rels if rel.startswith("nom:")]

    logging.info(f"[navidrome] Computing summaries for {len(filtered_rels)} tag types...")

    stats_by_tag = {}

    for idx, rel in enumerate(filtered_rels, 1):
        try:
            if idx % 10 == 0:
                logging.info(f"[navidrome] Progress: {idx}/{len(filtered_rels)} tags processed...")

            # Get value counts for this rel
            value_counts = db.tags.get_tag_value_counts(rel)
            total_count = sum(value_counts.values())

            # Infer type from first value
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

            # Build summary
            if tag_type in ("float", "integer"):
                values = list(value_counts.keys())
                if values:
                    summary = f"min={min(values)}, max={max(values)}, unique={len(values)}"
                else:
                    summary = "no values"
            else:
                summary = f"unique={len(value_counts)}"

            stats_by_tag[rel] = {
                "type": tag_type,
                "is_multivalue": len(value_counts) > 1,
                "summary": summary,
                "total_count": total_count,
            }
        except Exception as e:
            logging.error(f"[navidrome] Error computing summary for {rel}: {e}")
            stats_by_tag[rel] = {
                "type": "string",
                "is_multivalue": False,
                "summary": f"Error: {e!s}",
                "total_count": 0,
            }

    logging.info(f"[navidrome] Completed {len(stats_by_tag)} tag summaries")
    return stats_by_tag
