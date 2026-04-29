"""V027: add persistent index on library_files.last_tagged_at for velocity calculation."""

from __future__ import annotations

import contextlib
import logging

from arango.exceptions import IndexCreateError

from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.7"
DESCRIPTION: str = "Add persistent index on library_files.last_tagged_at for velocity/ETA query"


def upgrade(db: DatabaseLike) -> None:
    """Add a persistent index on library_files.last_tagged_at.

    The count_recently_tagged query filters files by last_tagged_at >= cutoff_ms.
    Without an index ArangoDB must scan every document in the collection.
    This index lets the query optimizer do a range scan and count cheaply.
    """
    with contextlib.suppress(IndexCreateError):
        db.collection("library_files").add_persistent_index(  # type: ignore[union-attr]
            fields=["last_tagged_at"]
        )
        logger.info("[V027] Added persistent index on library_files.last_tagged_at")
