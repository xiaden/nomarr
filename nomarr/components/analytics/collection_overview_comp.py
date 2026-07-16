"""Collection overview analytics - library stats and distributions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from nomarr.components.tagging.tag_stats_comp import (
    get_genre_distribution,
    get_library_stats,
    get_year_distribution,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class CollectionOverviewResult(TypedDict):
    """Result shape for compute_collection_overview."""

    stats: dict[str, Any]
    year_distribution: list[dict[str, Any]]
    genre_distribution: list[dict[str, Any]]


async def compute_collection_overview(
    db: Database,
    library_id: int | None = None,
) -> CollectionOverviewResult:
    """Get collection overview: library stats, year/genre distributions.

    Args:
        db: Database instance.
        library_id: Optional library id to filter by.

    """
    return {
        "stats": await get_library_stats(db, library_id),
        "year_distribution": await get_year_distribution(db, library_id),
        "genre_distribution": await get_genre_distribution(db, library_id, limit=None),
    }
