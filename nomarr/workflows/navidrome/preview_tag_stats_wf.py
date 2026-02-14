"""Preview tag statistics workflow.

This workflow computes statistics for all tags in the library, useful for
debugging and understanding tag data before generating Navidrome config.

Stats include a short_name for user-friendly display in Navidrome UI.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.helpers.tag_key_mapping import (
    is_versioned_ml_key,
    make_navidrome_field_name,
    make_short_tag_name,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def preview_tag_stats_workflow(db: Database, namespace: str = "nom") -> dict[str, dict[str, Any]]:
    """Preview statistics for all tags in the library.

    Returns stats for all tags: both standard tags (artist, album, year, etc.)
    and nomarr-namespaced tags (nom:mood-*, nom:effnet_*, etc.).

    Each tag stat includes:
    - type: string|number|integer
    - is_multivalue: bool
    - summary: string describing the tag values
    - total_count: number of files with this tag
    - short_name: user-friendly display name for Navidrome UI
    - field_name: TOML-safe field name for Navidrome config

    Uses a batched database query for performance (single query instead of N queries).

    Args:
        db: Database instance
        namespace: Tag namespace (default: "nom") — currently unused, kept for API compat

    Returns:
        Dict of tag_key -> stats dict

    """
    logger.info("[navidrome] Computing tag statistics (batched query)...")
    stats_by_tag = db.tags.get_all_tag_stats_batched()

    # Add short_name and field_name to each tag's stats
    for tag_key, stats in stats_by_tag.items():
        # Determine if numeric based on type
        is_numeric = stats.get("type") in ("number", "integer")
        short_name = make_short_tag_name(tag_key, is_numeric=is_numeric)
        field_name = make_navidrome_field_name(short_name)

        stats["short_name"] = short_name
        stats["field_name"] = field_name
        stats["is_versioned"] = is_versioned_ml_key(tag_key)

    logger.info(f"[navidrome] Completed {len(stats_by_tag)} tag summaries")
    return stats_by_tag
