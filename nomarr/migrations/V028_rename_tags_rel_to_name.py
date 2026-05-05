"""V028: rename tags.rel to tags.name."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, cast

from arango.exceptions import IndexCreateError, IndexDeleteError

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.8"
DESCRIPTION: str = "Rename tags field: rel → name"


def upgrade(db: DatabaseLike) -> None:
    """Rename the ``rel`` field to ``name`` on every document in the tags collection.

    The field was renamed to ``name`` to better reflect its role as the tag
    type key (e.g. ``"artist"``, ``"nom:mood-strict"``).  Documents that
    already have a ``name`` field (re-run safety) are left untouched.
    The stale ``rel`` field is dropped via ``keepNull: false``.
    """
    if not db.has_collection("tags"):  # type: ignore[union-attr]
        logger.info("[V028] Skipping — tags collection does not exist")
        return

    result = cast(
        "Cursor",
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN tags
                FILTER doc.rel != null AND doc.name == null
                UPDATE doc WITH { name: doc.rel, rel: null }
                IN tags
                OPTIONS { keepNull: false }
                COLLECT WITH COUNT INTO updated
                RETURN updated
            """,
        ),
    )
    updated = next(result, 0)
    logger.info("[V028] Renamed rel → name on %d tag documents", updated)

    # Drop stale indexes referencing the old field name and replace with name-based ones.
    coll = db.collection("tags")  # type: ignore[union-attr]
    for idx in coll.indexes():  # type: ignore[union-attr]
        if idx.get("type") == "persistent" and "rel" in (idx.get("fields") or []):
            with contextlib.suppress(IndexDeleteError):
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info("[V028] Dropped stale index %s from tags", idx["fields"])

    with contextlib.suppress(IndexCreateError):
        coll.add_persistent_index(fields=["name"])  # type: ignore[union-attr]
        logger.info("[V028] Added persistent index on tags.name")
    with contextlib.suppress(IndexCreateError):
        coll.add_persistent_index(fields=["name", "value"], unique=True)  # type: ignore[union-attr]
        logger.info("[V028] Added unique persistent index on tags(name, value)")
