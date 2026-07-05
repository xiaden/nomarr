"""Collection overview analytics - library stats and distributions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.tagging.tag_stats_comp import (
    get_genre_distribution,
    get_library_stats,
    get_year_distribution,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def compute_collection_overview(
    db: Database,
    library_id: str | None = None,
) -> dict[str, Any]:
    """Return collection overview: library stats, year and genre distributions."""
    return {
        "stats": get_library_stats(db, library_id),
        "year_distribution": get_year_distribution(db, library_id),
        "genre_distribution": get_genre_distribution(db, library_id, limit=None),
    }
