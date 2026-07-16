"""Conversion helpers for pgvector HNSW vector search and index parameters.

All functions are pure arithmetic with no side-effects and no nomarr imports.
"""

from __future__ import annotations

# ── pgvector HNSW constants ──────────────────────────────────────────
_HNSW_EF_SEARCH_MIN = 20
_HNSW_EF_CONSTRUCTION_MIN = 100
_HNSW_EF_CONSTRUCTION_MAX = 500
_HNSW_M = 16


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



