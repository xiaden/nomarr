"""Conversion helpers for vector search and index parameters.

Historically computed ArangoDB IVF parameters (nLists, nProbe) for Voronoi-cell
indexing.  The codebase has migrated to PostgreSQL pgvector with HNSW indexes,
so the live path now uses ``get_ef_search``, ``get_ef_construction``, and
``get_m``.  The legacy IVF functions are retained for migration compatibility
but are no longer used by any live code path.

All functions are pure arithmetic with no side-effects and no nomarr imports.
"""

from __future__ import annotations

from typing import TypedDict

# ── Legacy ArangoDB IVF constants ────────────────────────────────────
_NLISTS_FLOOR = 10
_NLISTS_CEIL = 4000

# ── pgvector HNSW constants ──────────────────────────────────────────
_HNSW_EF_SEARCH_MIN = 20
_HNSW_EF_CONSTRUCTION_MIN = 100
_HNSW_EF_CONSTRUCTION_MAX = 500
_HNSW_M = 16


def compute_nlists(doc_count: int, group_size: int = 15) -> int:
    """Derive the ArangoDB ``nLists`` parameter from a doc count and group size.

    .. deprecated::
        Legacy ArangoDB IVF parameters — no longer used by pgvector HNSW.
        Kept for migration compatibility.  Prefer pgvector HNSW params:
        :func:`get_ef_search`, :func:`get_ef_construction`, :func:`get_m`.

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

    .. deprecated::
        Legacy ArangoDB IVF parameters — no longer used by pgvector HNSW.
        Kept for migration compatibility.  Prefer pgvector HNSW params:
        :func:`get_ef_search`, :func:`get_ef_construction`, :func:`get_m`.

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


# ── pgvector HNSW parameter helpers ──────────────────────────────────


def get_ef_search(doc_count: int) -> int:
    """Compute the pgvector HNSW ``ef_search`` parameter for query-time width.

    ``ef_search`` controls how many candidates are examined during an ANN
    query.  Higher values improve recall at the cost of latency.

    Guidelines:
        - Small collections (~1K docs): 40
        - Medium (~10K): 100
        - Large (~100K+): 200 to 400

    Args:
        doc_count: Total number of vectors in the collection.

    Returns:
        ef_search value (minimum 20).  Returns 100 for unknown/zero counts
        as a sensible medium-collection default.

    """
    if doc_count <= 0:
        return 100
    if doc_count <= 1_000:
        return 40
    if doc_count <= 10_000:
        return 100
    if doc_count <= 100_000:
        return 200
    return 400


def get_ef_construction(doc_count: int) -> int:
    """Compute the pgvector HNSW ``ef_construction`` parameter for build-time quality.

    ``ef_construction`` controls the width of search during index creation.
    Higher values produce a better-quality graph but slower index builds.

    Guidelines:
        - Minimum: 100
        - Large collections (~100K+): up to 500

    Args:
        doc_count: Total number of vectors in the collection.

    Returns:
        ef_construction value (100 to 500).  Returns 200 for unknown/zero counts.

    """
    if doc_count <= 0:
        return 200
    if doc_count <= 1_000:
        return _HNSW_EF_CONSTRUCTION_MIN
    if doc_count <= 10_000:
        return 200
    if doc_count <= 100_000:
        return 300
    return _HNSW_EF_CONSTRUCTION_MAX


def get_m() -> int:
    """Return the standard HNSW ``M`` parameter (connections per node).

    ``M=16`` is the standard value for pgvector HNSW indexes, balancing
    recall quality and memory usage.

    Returns:
        16 (standard HNSW M value).

    """
    return _HNSW_M


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
