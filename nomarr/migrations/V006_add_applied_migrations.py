"""V006: Add applied_migrations collection.

This is the bootstrap migration that establishes the migration tracking
infrastructure itself. The applied_migrations collection is created by
ensure_schema() (which runs before migrations), so this migration only
needs to verify it exists and set the schema version.

This migration bridges the gap from SCHEMA_VERSION 5 (pre-migration system)
to SCHEMA_VERSION 6 (migration-aware).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 5
SCHEMA_VERSION_AFTER: int = 6
DESCRIPTION: str = "Add applied_migrations collection for migration tracking"


def upgrade(db: DatabaseLike) -> None:
    """Verify applied_migrations collection exists.

    The collection is created by ensure_schema() which runs before migrations.
    This migration serves as the anchor point for the migration version chain,
    bridging from the pre-migration era (v5) to the migration-aware era (v6).

    Args:
        db: ArangoDB database handle.

    Raises:
        RuntimeError: If the applied_migrations collection was not created
            by ensure_schema().

    """
    if not db.has_collection("applied_migrations"):
        msg = (
            "applied_migrations collection not found. "
            "This should have been created by ensure_schema(). "
            "Check arango_bootstrap_comp.py for the collection definition."
        )
        raise RuntimeError(msg)

    logger.info(
        "Migration V006: applied_migrations collection verified. "
        "Migration tracking system is now active.",
    )
