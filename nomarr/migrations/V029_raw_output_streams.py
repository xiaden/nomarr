"""V029: add canonical raw ML output stream collections."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from arango.exceptions import CollectionCreateError, IndexCreateError

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.9"
DESCRIPTION: str = "Add canonical raw ML output stream collections"


def upgrade(db: DatabaseLike) -> None:
    """Create canonical raw-stream persistence collections and indexes.

    Adds the ``ml_output_streams`` document collection plus the
    ``file_has_output_stream`` and ``output_has_stream`` edge collections.
    The migration is additive and idempotent so later phases can cut callers
    over without breaking databases already on older canonical stats storage.
    """
    if not db.has_collection("ml_output_streams"):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("ml_output_streams")  # type: ignore[union-attr]
            logger.info("[V029] Created document collection ml_output_streams")

    for coll_name in ("file_has_output_stream", "output_has_stream"):
        if not db.has_collection(coll_name):  # type: ignore[union-attr]
            with contextlib.suppress(CollectionCreateError):
                db.create_collection(coll_name, edge=True)  # type: ignore[union-attr]
                logger.info("[V029] Created edge collection %s", coll_name)

        coll = db.collection(coll_name)  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_from", "_to"], unique=True)  # type: ignore[union-attr]
            logger.info("[V029] Added unique persistent index on %s(_from, _to)", coll_name)
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_from"])  # type: ignore[union-attr]
            logger.info("[V029] Added persistent index on %s._from", coll_name)
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_to"])  # type: ignore[union-attr]
            logger.info("[V029] Added persistent index on %s._to", coll_name)
