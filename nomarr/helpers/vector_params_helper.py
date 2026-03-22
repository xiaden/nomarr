"""Conversion helpers for user-friendly vector search parameters.

nLists and nProbe are ArangoDB vector-index internals; users think about
group size ("how many songs per neighbourhood") and thoroughness
("what percentage of neighbourhoods to scan").

All functions are pure arithmetic with no side-effects and no nomarr imports.
"""

from __future__ import annotations

from typing import TypedDict

_NLISTS_FLOOR = 10
_NLISTS_CEIL = 4000


def compute_nlists(doc_count: int, group_size: int = 15) -> int:
    """Derive the ArangoDB ``nLists`` parameter from a doc count and group size.

    Each Voronoi cell ("list") covers approximately *group_size* documents.
    The result is clamped to [10, 4000].

    Args:
        doc_count: Total number of vectors in the collection.
        group_size: Target number of documents per neighbourhood.

    Returns:
        Optimal nLists value (10-4000).
    """
    if doc_count <= 0:
        return _NLISTS_FLOOR
    nlists = doc_count // max(1, group_size)
    return max(_NLISTS_FLOOR, min(_NLISTS_CEIL, nlists))


def compute_nprobe(nlists: int, thoroughness_pct: int = 10) -> int:
    """Derive the ArangoDB ``nProbe`` parameter from nLists and a thoroughness %.

    nProbe is the number of Voronoi cells probed per query.  A higher value
    improves recall at the cost of latency.

    Args:
        nlists: Number of Voronoi cells (from :func:`compute_nlists`).
        thoroughness_pct: Percentage of cells to probe (1-100).

    Returns:
        nProbe value, at least 1 and at most *nlists*.
    """
    if nlists <= 0:
        return 1
    nprobe = nlists * thoroughness_pct // 100
    return max(1, min(nlists, nprobe))


class VectorSearchDescription(TypedDict):
    """Human-readable breakdown of vector search parameters."""

    songs_per_group: int
    num_groups: int
    groups_searched: int
    songs_checked: int
    pct_searched: float


def describe_search_params(
    doc_count: int,
    group_size: int,
    thoroughness_pct: int,
) -> VectorSearchDescription:
    """Compute a human-readable description of current vector search settings.

    Used by the frontend explainer (Part C) to display "what this means".

    Args:
        doc_count: Total number of vectors in the collection.
        group_size: Target number of documents per neighbourhood.
        thoroughness_pct: Percentage of neighbourhoods to probe.

    Returns:
        Dict with derived values suitable for UI display.
    """
    nlists = compute_nlists(doc_count, group_size)
    nprobe = compute_nprobe(nlists, thoroughness_pct)
    songs_per_group = max(1, doc_count // nlists) if nlists > 0 else doc_count
    songs_checked = nprobe * songs_per_group
    pct_searched = (songs_checked / doc_count * 100) if doc_count > 0 else 0.0

    return VectorSearchDescription(
        songs_per_group=songs_per_group,
        num_groups=nlists,
        groups_searched=nprobe,
        songs_checked=min(songs_checked, doc_count),
        pct_searched=min(pct_searched, 100.0),
    )
