"""V010: Add vram_promises collection for fleet-aware VRAM coordination.

Background
----------
Multiple discovery workers each warm their ONNX model cache independently.
Without coordination, two workers can both believe they have enough VRAM,
load their full model sets, and together exceed GPU capacity — causing
inference-time OOM crashes.

Fix
---
A shared ``vram_promises`` collection acts as a fleet-wide promise registry.
Before loading any model onto GPU, a worker atomically checks all existing
promises, verifies the new model fits within headroom, and INSERTs only if
fit is confirmed. ArangoDB write serialization acts as the distributed lock.

This migration creates the ``vram_promises`` collection and a TTL index on
``last_seen_ms`` for stale promise cleanup (crash recovery). The TTL index
serves as a distant fallback; the primary cleanup mechanism is
``VramPromisesOperations.reap_stale()`` called periodically by workers.

Note on TTL field units
-----------------------
``last_seen_ms`` stores Unix timestamps in milliseconds, consistent with the
codebase convention (``now_ms().value``). The ArangoDB TTL index treats the
field value as a Unix timestamp in *seconds*, so the stored ms value is
interpreted as a date ~57,000 years in the future — meaning ArangoDB's
automatic TTL expiry will not fire. Stale cleanup is performed exclusively
by ``VramPromisesOperations.reap_stale()`` via AQL arithmetic.

Forward-only; no downgrade path.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 9
SCHEMA_VERSION_AFTER: int = 10
DESCRIPTION: str = "Add vram_promises collection for fleet-aware VRAM coordination"


def upgrade(db: DatabaseLike) -> None:  # type: ignore[override]
    """Create the vram_promises collection with a TTL index.

    Idempotent — safe to run multiple times.

    Args:
        db: ArangoDB database handle.

    """
    from arango.exceptions import CollectionCreateError, IndexCreateError

    # Create the collection if it doesn't exist
    if not db.has_collection("vram_promises"):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("vram_promises")  # type: ignore[union-attr]
        logger.info("Migration V010: Created vram_promises collection")
    else:
        logger.info("Migration V010: vram_promises collection already exists — skipping creation")

    # Add TTL index on last_seen_ms for stale-promise cleanup
    # Note: ArangoDB interprets the field as seconds; since we store milliseconds,
    # automatic TTL will not fire. Cleanup is via VramPromisesOperations.reap_stale().
    try:
        coll = db.collection("vram_promises")  # type: ignore[union-attr]
        coll.add_ttl_index(fields=["last_seen_ms"], expiry_time=300)  # type: ignore[union-attr]
        logger.info("Migration V010: Created TTL index on last_seen_ms")
    except IndexCreateError as exc:
        if exc.http_code == 409:
            logger.info("Migration V010: TTL index already exists — skipping")
        else:
            raise

    logger.info("Migration V010: Complete")
