"""Preview tag statistics workflow.

This workflow computes statistics for all tags in the library, useful for
debugging and understanding tag data before generating Navidrome config.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def preview_tag_stats_workflow(db: Database, namespace: str = "nom") -> dict[str, dict[str, Any]]:
    """Preview statistics for all tags in the library.

    Returns stats for all tags: both standard tags (artist, album, year, etc.)
    and nomarr-namespaced tags (nom:mood-*, nom:effnet_*, etc.).

    Uses a batched database query for performance (single query instead of N queries).

    Args:
        db: Database instance
        namespace: Tag namespace (default: "nom") — currently unused, kept for API compat

    Returns:
        Dict of tag_key -> stats dict (type, is_multivalue, summary, count)

    """
    logger.info("[navidrome] Computing tag statistics (batched query)...")
    stats_by_tag = db.tags.get_all_tag_stats_batched()
    logger.info(f"[navidrome] Completed {len(stats_by_tag)} tag summaries")
    return stats_by_tag
