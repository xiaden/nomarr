"""V024: add persistent index on library_files.scanned_at for recent-activity query."""

from __future__ import annotations

import contextlib
import logging

from arango.exceptions import IndexCreateError

from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.4"
DESCRIPTION: str = "Add persistent index on library_files.scanned_at to speed up recent-activity sort"


def upgrade(db: DatabaseLike) -> None:
    """Add a persistent index on library_files.scanned_at.

    The get_recently_processed query sorts all tagged files by scanned_at DESC
    and limits to N results.  Without an index ArangoDB must collect and sort
    every tagged document.  This index lets the query optimizer do a reverse
    scan and stop after N results.
    """
    with contextlib.suppress(IndexCreateError):
        db.collection("library_files").add_persistent_index(  # type: ignore[union-attr]
            fields=["scanned_at"]
        )
        logger.info("[V024] Added persistent index on library_files.scanned_at")
