"""V008: Backfill vector_n (L2-normalized) field on cold vector collections.

Background
----------
``APPROX_NEAR_COSINE`` in ArangoDB normalizes the **query** vector internally
but returns ``dot(q̂, raw_stored_vec)`` as the score rather than true cosine
similarity.  Because stored embeddings have variable magnitudes (effnet spread
~5.75x, musicnn ~3.21x) the scores can exceed 1.0 and ranking is corrupted.

Fix
---
A new field ``vector_n`` (the L2-normalized copy of ``vector``) is stored
alongside the raw ``vector`` in every document.  The vector index is rebuilt
to point at ``vector_n`` so that ``APPROX_NEAR_COSINE(doc.vector_n, @q)``
returns true cosine similarity in [-1, 1].

This migration:
  1. Backfills ``vector_n`` for all existing cold documents that lack it
     (idempotent: skips docs that already have the field).
  2. Drops the existing vector index (indexed on ``vector``) for each cold
     collection and rebuilds it on ``vector_n`` using the same dimension and
     nLists from the original index.

Forward-only; no dowgrade path.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 7
SCHEMA_VERSION_AFTER: int = 8
DESCRIPTION: str = (
    "Backfill vector_n (L2-normalized) field on cold vector collections "
    "and rebuild vector indexes to use vector_n"
)

_VECTORS_TRACK_COLD_PREFIX = "vectors_track_cold__"


def upgrade(db: DatabaseLike) -> None:
    """Backfill vector_n and rebuild vector indexes for all cold collections.

    Steps per cold collection:
    1. AQL UPDATE: compute L2-normalized vector and store as ``vector_n`` on all
       documents that do not yet have the field (idempotent).
    2. Read existing vector index params (dimension, nLists).
    3. Drop existing vector index.
    4. Rebuild vector index on ``vector_n`` with same params.

    Args:
        db: ArangoDB database handle.

    """
    collections = db.collections()  # type: ignore[union-attr]
    if collections is None:
        logger.warning("Migration V008: Could not list collections. Skipping.")
        return

    cold_colls = sorted(
        c["name"]
        for c in collections  # type: ignore[union-attr]
        if c["name"].startswith(_VECTORS_TRACK_COLD_PREFIX)
    )

    if not cold_colls:
        logger.info("Migration V008: No cold vector collections found. Nothing to do.")
        return

    logger.info(
        "Migration V008: Processing %d cold collection(s): %s",
        len(cold_colls),
        ", ".join(cold_colls),
    )

    for coll_name in cold_colls:
        _backfill_vector_n(db, coll_name)
        _rebuild_index_on_vector_n(db, coll_name)
        logger.info("Migration V008: Completed for %s", coll_name)

    logger.info("Migration V008: All cold collections processed successfully.")


_BACKFILL_BATCH_SIZE = 500


def _backfill_vector_n(db: DatabaseLike, coll_name: str) -> None:
    """Add vector_n to docs that are missing it via batched AQL UPDATEs.

    Processes documents in batches of _BACKFILL_BATCH_SIZE to avoid hitting
    the HTTP read timeout on large collections.  Each batch query completes
    well within the 60 s client timeout even for high-dimensional embeddings.

    Uses AQL array inline expressions to compute the L2 norm and normalize
    each element.  The FILTER ensures idempotency: already-normalized docs
    are skipped without re-computation.

    Args:
        db: ArangoDB database handle.
        coll_name: Cold collection name.

    """
    logger.info("Migration V008: Backfilling vector_n in %s …", coll_name)

    # Count docs missing vector_n before update
    pre_cursor = db.aql.execute(  # type: ignore[union-attr]
        f"""
        RETURN LENGTH(
            FOR doc IN {coll_name}
                FILTER !HAS(doc, "vector_n")
                RETURN 1
        )
        """
    )
    missing_count = next(iter(pre_cursor))  # type: ignore[arg-type]
    logger.info(
        "Migration V008: %s has %d docs missing vector_n", coll_name, missing_count
    )

    if missing_count == 0:
        logger.info("Migration V008: Skipping backfill for %s (all docs have vector_n)", coll_name)
        return

    # Process in batches to avoid HTTP read timeout on large collections.
    total_updated = 0
    batch_num = 0
    remaining = missing_count
    while remaining > 0:
        batch_num += 1
        db.aql.execute(  # type: ignore[union-attr]
            f"""
            FOR doc IN {coll_name}
                FILTER !HAS(doc, "vector_n")
                LIMIT @batch_size
                LET norm = SQRT(SUM(doc.vector[* RETURN CURRENT * CURRENT]))
                UPDATE doc WITH {{ vector_n: doc.vector[* RETURN CURRENT / norm] }}
                IN {coll_name}
            """,
            bind_vars={"batch_size": _BACKFILL_BATCH_SIZE},  # type: ignore[dict-item]
        )

        # Check how many remain after this batch
        remaining_cursor = db.aql.execute(  # type: ignore[union-attr]
            f"""
            RETURN LENGTH(
                FOR doc IN {coll_name}
                    FILTER !HAS(doc, "vector_n")
                    RETURN 1
            )
            """
        )
        remaining = next(iter(remaining_cursor))  # type: ignore[arg-type]
        batch_updated = missing_count - remaining - total_updated
        total_updated += batch_updated
        logger.info(
            "Migration V008: Batch %d complete — %d updated this batch, %d remaining in %s",
            batch_num,
            batch_updated,
            remaining,
            coll_name,
        )

    logger.info(
        "Migration V008: Backfilled vector_n for %d docs in %s",
        total_updated,
        coll_name,
    )


def _rebuild_index_on_vector_n(db: DatabaseLike, coll_name: str) -> None:
    """Drop existing vector index and rebuild it pointing at vector_n.

    Reads dimension and nLists from the existing vector index before dropping
    so the rebuilt index is equivalent in all parameters except the indexed field.

    Args:
        db: ArangoDB database handle.
        coll_name: Cold collection name.

    """
    coll = db.collection(coll_name)  # type: ignore[union-attr]
    existing_indexes = coll.indexes()  # type: ignore[union-attr]

    vector_idx = next(
        (idx for idx in existing_indexes if idx.get("type") == "vector"),  # type: ignore[union-attr]
        None,
    )

    if vector_idx is None:
        logger.info(
            "Migration V008: No vector index found on %s — skipping index rebuild",
            coll_name,
        )
        return

    # Check if already pointing at vector_n (idempotency)
    indexed_fields = vector_idx.get("fields", [])
    if "vector_n" in indexed_fields:
        logger.info(
            "Migration V008: Vector index on %s already uses vector_n — skipping rebuild",
            coll_name,
        )
        return

    params = vector_idx.get("params", {})
    embed_dim = params.get("dimension")
    nlists = params.get("nLists")

    if not embed_dim or not nlists:
        logger.warning(
            "Migration V008: Could not read index params from %s (dim=%s, nLists=%s). "
            "Skipping index rebuild.",
            coll_name,
            embed_dim,
            nlists,
        )
        return

    idx_id = vector_idx.get("id")
    logger.info(
        "Migration V008: Dropping vector index %s from %s (was on %s, dim=%d, nLists=%d)",
        idx_id,
        coll_name,
        indexed_fields,
        embed_dim,
        nlists,
    )
    if idx_id is None:
        logger.warning(
            "Migration V008: Vector index on %s has no id, cannot drop. Skipping.",
            coll_name,
        )
        return
    coll.delete_index(str(idx_id))  # type: ignore[union-attr]

    logger.info(
        "Migration V008: Rebuilding vector index on %s (field=vector_n, dim=%d, nLists=%d)",
        coll_name,
        embed_dim,
        nlists,
    )
    coll.add_index(  # type: ignore[union-attr]
        {
            "type": "vector",
            "fields": ["vector_n"],
            "params": {
                "metric": "cosine",
                "dimension": embed_dim,
                "nLists": nlists,
            },
        }
    )
    logger.info(
        "Migration V008: Vector index rebuilt on vector_n for %s", coll_name
    )
