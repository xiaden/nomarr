"""Unit tests for vector_params_helper.

Tests for ``compute_nlists``, ``compute_nprobe``, and ``describe_search_params``
have been removed because those ArangoDB-era functions were deleted in the
pgvector migration.  The remaining helpers (``get_ef_search``,
``get_ef_construction``, ``get_m``) are pure constants/arithmetic with no
external dependencies.
"""

from __future__ import annotations

# ── pgvector HNSW helpers still live in ``vector_params_helper.py`` but are
#    trivial arithmetic wrappers.  Tests can be added here once any of them
#    gain non-trivial logic.
