"""V034: Add missing indexes for query performance.

Adds indexes on frequently filtered fields:
- worker_claims.file_id (filtered in delete_claims_for_files)
- navidrome_tracks.userid (filtered in playcount operations)
- navidrome_playcounts.userid (single-field index for existence checks)
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from arango.exceptions import IndexCreateError

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.34"
DESCRIPTION: str = "Add missing indexes for query performance"


def upgrade(db: DatabaseLike) -> None:
    """Add missing indexes for query performance."""
    logger.info("[V034] Adding indexes for query performance")

    # Index on worker_claims.file_id for delete_claims_for_files
    with contextlib.suppress(IndexCreateError):
        db.collection("worker_claims").add_persistent_index(fields=["file_id"])  # type: ignore[union-attr]
        logger.info("[V034] Created index on worker_claims.file_id")

    # Index on navidrome_tracks.userid for playcount operations
    with contextlib.suppress(IndexCreateError):
        db.collection("navidrome_tracks").add_persistent_index(fields=["userid"])  # type: ignore[union-attr]
        logger.info("[V034] Created index on navidrome_tracks.userid")

    # Single-field index on navidrome_playcounts.userid for existence checks
    with contextlib.suppress(IndexCreateError):
        db.collection("navidrome_playcounts").add_persistent_index(fields=["userid"])  # type: ignore[union-attr]
        logger.info("[V034] Created index on navidrome_playcounts.userid")

    logger.info("[V034] Migration complete")
