"""V016: Add file_states vertices and file_has_state edge collection.

Background
----------
The ``library_files`` collection has accumulated 14 flat state fields spanning
scan lifecycle, ML tagging, calibration, and reconciliation.  This migration
introduces a graph-native state model:

- **``file_states``** — vertex collection with fixed state documents
  (``ml_tagged``, ``calibrated``, ``reconciled``).  Presence of an edge from a
  file to a state vertex means the file has reached that processing stage.
  Absence means it still needs processing.

- **``file_has_state``** — edge collection connecting ``library_files/*`` →
  ``file_states/*``.  Edge documents carry per-state attributes such as
  ``version``, ``hash``, ``mode``, ``written_at``, etc.

This migration only creates the schema.  A follow-up step (P2-S2 in the plan)
populates edges from existing flat fields so both representations coexist
during the transition period.

Edge document schemas
---------------------

**ml_tagged edge:**
``{_from: library_files/X, _to: file_states/ml_tagged, version: str, tagged_at: int}``

**calibrated edge:**
``{_from: library_files/X, _to: file_states/calibrated, hash: str, calibrated_at: int}``

**reconciled edge:**
``{_from: library_files/X, _to: file_states/reconciled, mode: str,
  calibration_hash: str | null, written_at: int, has_namespace: bool}``

Indexes on ``file_has_state``
----------------------------

- Unique persistent on ``(_from, _to)`` — one state per file per type
- Persistent on ``_to`` — efficient state-type lookups (e.g. "all ml_tagged")

Forward-only; no downgrade path.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 15
SCHEMA_VERSION_AFTER: int = 16
DESCRIPTION: str = "Add file_states vertices and file_has_state edge collection"

_STATE_KEYS: list[str] = ["ml_tagged", "calibrated", "reconciled"]


def upgrade(db: DatabaseLike) -> None:  # type: ignore[override]
    """Create file_states vertex collection, file_has_state edge collection, and indexes.

    Idempotent — safe to run multiple times.

    Args:
        db: ArangoDB database handle.
    """
    from arango.exceptions import CollectionCreateError, DocumentInsertError, IndexCreateError

    # ------------------------------------------------------------------
    # file_states — vertex collection with fixed state documents
    # ------------------------------------------------------------------
    if not db.has_collection("file_states"):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("file_states")  # type: ignore[union-attr]
        logger.info("Migration V016: Created file_states collection")
    else:
        logger.info("Migration V016: file_states already exists — skipping creation")

    coll = db.collection("file_states")  # type: ignore[union-attr]
    for key in _STATE_KEYS:
        try:
            coll.insert({"_key": key})  # type: ignore[union-attr]
            logger.info("Migration V016: Inserted file_states/%s", key)
        except DocumentInsertError as exc:
            if exc.http_code == 409:  # already exists
                logger.info("Migration V016: file_states/%s already exists — skipping", key)
            else:
                raise

    # ------------------------------------------------------------------
    # file_has_state — edge collection
    # ------------------------------------------------------------------
    if not db.has_collection("file_has_state"):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("file_has_state", edge=True)  # type: ignore[union-attr]
        logger.info("Migration V016: Created file_has_state edge collection")
    else:
        logger.info("Migration V016: file_has_state already exists — skipping creation")

    # ------------------------------------------------------------------
    # Indexes on file_has_state
    # ------------------------------------------------------------------
    edge_coll = db.collection("file_has_state")  # type: ignore[union-attr]

    # Unique constraint: one state per file per type
    try:
        edge_coll.add_persistent_index(  # type: ignore[union-attr]
            fields=["_from", "_to"],
            unique=True,
            sparse=False,
        )
        logger.info("Migration V016: Created unique persistent index on file_has_state(_from, _to)")
    except IndexCreateError as exc:
        if exc.http_code == 409:
            logger.info("Migration V016: file_has_state(_from, _to) index already exists — skipping")
        else:
            raise

    # State-type lookup index (e.g. all files in ml_tagged state)
    try:
        edge_coll.add_persistent_index(  # type: ignore[union-attr]
            fields=["_to"],
            unique=False,
            sparse=False,
        )
        logger.info("Migration V016: Created persistent index on file_has_state(_to)")
    except IndexCreateError as exc:
        if exc.http_code == 409:
            logger.info("Migration V016: file_has_state(_to) index already exists — skipping")
        else:
            raise

    # ------------------------------------------------------------------
    # Populate edges from existing library_files flat state fields
    # ------------------------------------------------------------------
    _populate_edges(db)

    logger.info("Migration V016: Complete")



def _populate_edges(db: DatabaseLike) -> None:
    """Backfill file_has_state edges from existing flat fields on library_files.

    Uses INSERT ... OPTIONS { ignoreErrors: true } so the unique (_from, _to) index
    silently skips duplicates, making this idempotent.

    Args:
        db: ArangoDB database handle.
    """
    from nomarr.helpers.time_helper import now_ms

    migration_ts = now_ms().value

    # ml_tagged: files with tagged == true
    result = db.aql.execute(  # type: ignore[union-attr]
        """
        FOR file IN library_files
            FILTER file.tagged == true
            INSERT {
                _from: file._id,
                _to: "file_states/ml_tagged",
                version: file.tagged_version,
                tagged_at: file.last_tagged_at
            } INTO file_has_state
            OPTIONS { ignoreErrors: true }
            COLLECT WITH COUNT INTO cnt
            RETURN cnt
        """,
    )
    count = next(result, 0)  # type: ignore[arg-type]
    logger.info("Migration V016: Populated %s ml_tagged edges", count)

    # calibrated: files with calibration_hash != null
    result = db.aql.execute(  # type: ignore[union-attr]
        """
        FOR file IN library_files
            FILTER file.calibration_hash != null
            INSERT {
                _from: file._id,
                _to: "file_states/calibrated",
                hash: file.calibration_hash,
                calibrated_at: @migration_ts
            } INTO file_has_state
            OPTIONS { ignoreErrors: true }
            COLLECT WITH COUNT INTO cnt
            RETURN cnt
        """,
        bind_vars=cast("dict[str, Any]", {"migration_ts": migration_ts}),
    )
    count = next(result, 0)  # type: ignore[arg-type]
    logger.info("Migration V016: Populated %s calibrated edges", count)

    # reconciled: files with last_written_mode != null
    result = db.aql.execute(  # type: ignore[union-attr]
        """
        FOR file IN library_files
            FILTER file.last_written_mode != null
            INSERT {
                _from: file._id,
                _to: "file_states/reconciled",
                mode: file.last_written_mode,
                calibration_hash: file.last_written_calibration_hash,
                written_at: file.last_written_at,
                has_namespace: file.has_nomarr_namespace == true
            } INTO file_has_state
            OPTIONS { ignoreErrors: true }
            COLLECT WITH COUNT INTO cnt
            RETURN cnt
        """,
    )
    count = next(result, 0)  # type: ignore[arg-type]
    logger.info("Migration V016: Populated %s reconciled edges", count)
