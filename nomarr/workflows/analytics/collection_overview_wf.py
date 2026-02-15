"""Workflow for computing collection overview analytics.

Orchestrates persistence queries for library stats, year/genre distributions.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def collection_overview_workflow(
    db: Database, library_id: str | None = None,
) -> dict[str, Any]:
    """Get collection overview data for Insights tab.

    Orchestrates library stats, year/genre distributions.

    Args:
        db: Database instance.
        library_id: Optional library _id to filter by.

    Returns:
        Dict with: stats, year_distribution, genre_distribution
    """
    # Step 1: Get aggregate library statistics
    stats = db.tags.get_library_stats(library_id)

    # Step 2: Get year distribution
    years = db.tags.get_year_distribution(library_id)

    # Step 3: Get genre distribution (all genres)
    genres = db.tags.get_genre_distribution(library_id, limit=None)

    return {
        "stats": stats,
        "year_distribution": years,
        "genre_distribution": genres,
    }
