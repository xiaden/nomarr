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
    tag_keys = db.library_tags.get_unique_tag_keys()
    namespace_prefix = f"{namespace}:"
    filtered_tags = [tag for tag in tag_keys if tag.startswith(namespace_prefix)]

    logging.info(f"[navidrome] Computing summaries for {len(filtered_tags)} tags...")

    stats_by_tag = {}

    for idx, tag_key in enumerate(filtered_tags, 1):
        try:
            if idx % 10 == 0:
                logging.info(f"[navidrome] Progress: {idx}/{len(filtered_tags)} tags processed...")

            summary = db.library_tags.get_tag_summary(tag_key)

            stats_by_tag[tag_key] = {
                "type": summary["type"],
                "is_multivalue": summary["is_multivalue"],
                "summary": summary["summary"],
                "total_count": summary["total_count"],
            }
        except Exception as e:
            logging.error(f"[navidrome] Error computing summary for {tag_key}: {e}")
            # Provide fallback data so one error doesn't break everything
            stats_by_tag[tag_key] = {
                "type": "string",
                "is_multivalue": False,
                "summary": f"Error: {e!s}",
                "total_count": 0,
            }

    logging.info(f"[navidrome] Completed {len(stats_by_tag)} tag summaries")
    return stats_by_tag
