"""Collection overview analytics - library stats and distributions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from nomarr.components.tagging.tag_stats_comp import (
    get_genre_distribution,
    get_library_stats,
    get_year_distribution,
)

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database


class CollectionOverviewResult(TypedDict):
    """Result shape for compute_collection_overview."""

    stats: dict[str, Any]
    year_distribution: list[dict[str, Any]]
    genre_distribution: list[dict[str, Any]]


def compute_collection_overview(
    db: Database,
    library: Library | None = None,
) -> CollectionOverviewResult:
    """Get collection overview: library stats, year/genre distributions.

    Args:
        db: Database instance.
        library: Optional domain ``Library`` (natural identity) to filter by.

    """
    return {
        "stats": get_library_stats(db, library),
        "year_distribution": get_year_distribution(db, library),
        "genre_distribution": get_genre_distribution(db, library, limit=None),
    }
