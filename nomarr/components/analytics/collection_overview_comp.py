"""Collection overview analytics - library stats and distributions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def compute_collection_overview(
    db: Database, library_id: str | None = None,
) -> dict[str, Any]:
    """Get collection overview: library stats, year/genre distributions.

    Args:
        db: Database instance.
        library_id: Optional library _id to filter by.

    Returns:
        Dict with: stats, year_distribution, genre_distribution
    """
    return {
        "stats": db.tags.get_library_stats(library_id),
        "year_distribution": db.tags.get_year_distribution(library_id),
        "genre_distribution": db.tags.get_genre_distribution(library_id, limit=None),
    }
