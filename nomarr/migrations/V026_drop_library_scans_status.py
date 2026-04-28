"""V026: drop the dead status field from library_scans."""

from __future__ import annotations

import logging

from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.6"
DESCRIPTION: str = "Drop dead status field from library_scans (pipeline state is source of truth)"


def upgrade(db: DatabaseLike) -> None:
    """Remove the legacy status field from library_scans documents."""
    if not db.has_collection("library_scans"):  # type: ignore[union-attr]
        logger.info("[V026] Skipping library_scans status cleanup because library_scans does not exist")
        return

    db.aql.execute(  # type: ignore[union-attr]
        """
        FOR doc IN library_scans
            UPDATE doc WITH { status: null } IN library_scans
            OPTIONS { keepNull: false }
        """
    )

    logger.info("[V026] Dropped dead status field from library_scans")
