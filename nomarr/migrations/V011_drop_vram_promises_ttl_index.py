"""V011: Drop the TTL index on vram_promises.last_seen_ms.

Background
----------
V010 added a TTL index on ``vram_promises.last_seen_ms`` as a crash-recovery
fallback. This was a design mistake for two reasons:

1. The index is non-functional: ``last_seen_ms`` stores Unix timestamps in
   milliseconds (e.g., 1740000000000), but ArangoDB interprets TTL field
   values as Unix timestamps in *seconds*. The stored values correspond to
   dates ~57,000 years in the future, so the index never fires.

2. The design is wrong: VRAM promises have explicit owners (stable worker IDs).
   Cleanup is the owner's responsibility — on worker death (``WorkerSystemService``
   clears via ``release_worker_promises``) and on worker startup (the worker
   clears its own stale promises from a previous crash). A TTL-based background
   reaper would evict valid long-running model loads as false positives.

Forward-only; no downgrade path.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 10
SCHEMA_VERSION_AFTER: int = 11
DESCRIPTION: str = "Drop broken TTL index on vram_promises.last_seen_ms"


def upgrade(db: DatabaseLike) -> None:  # type: ignore[override]
    """Drop the TTL index on vram_promises if it exists.

    Idempotent — safe to run even if the index was already removed.

    Args:
        db: ArangoDB database handle.

    """
    if not db.has_collection("vram_promises"):  # type: ignore[union-attr]
        logger.info("Migration V011: vram_promises collection does not exist — nothing to do")
        return

    coll = db.collection("vram_promises")  # type: ignore[union-attr]
    indexes = coll.indexes()  # type: ignore[union-attr]
    assert isinstance(indexes, list)

    ttl_index = next(
        (idx for idx in indexes if idx.get("type") == "ttl" and "last_seen_ms" in idx.get("fields", [])),
        None,
    )

    if ttl_index is None:
        logger.info("Migration V011: TTL index not found — already removed or never created")
    else:
        coll.delete_index(ttl_index["id"])  # type: ignore[union-attr]
        logger.info("Migration V011: Dropped TTL index on last_seen_ms (id=%s)", ttl_index["id"])

    logger.info("Migration V011: Complete")
