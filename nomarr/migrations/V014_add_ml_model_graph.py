"""V013: Add ml_models, ml_model_outputs, and tag_model_output collections.

Background
----------
The ML pipeline previously read class labels from co-located ``.json`` sidecar
files that were created for the essentia-tensorflow era. This design is not
sustainable: MTG ships ONNX models with no embedded labels, and users cannot
edit ONNX files to supply missing label information.

Replacement Architecture
------------------------
Model heads and their per-output labels are stored as first-class graph
vertices in ArangoDB:

- ``ml_models`` — one document per ONNX head file; records the path,
  backbone, head type, and whether all outputs have been labeled by the user
  or seeded from in-code defaults.

- ``ml_model_outputs`` — one document per output dimension of each head;
  records the label string, whether the output is the "positive" class, and
  an optional display hint sourced from the ONNX output node name.

- ``tag_model_output`` — edge collection; each tag document written during
  inference gains an outbound edge to the ``ml_model_outputs`` vertex that
  produced it, carrying the raw model score.  This edge is used both for
  calibration traceability and to determine whether a tag is "claimed" by
  a live model output (orphan cleanup condition).

Renaming a label is a single ``UPDATE`` on the ``ml_model_outputs`` vertex;
*all* tags that traverse the edge automatically resolve the new name without
any backfill.

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
SCHEMA_VERSION_BEFORE: int = 13
SCHEMA_VERSION_AFTER: int = 14
DESCRIPTION: str = "Add ml_models, ml_model_outputs vertex collections and tag_model_output edge collection"


def upgrade(db: DatabaseLike) -> None:  # type: ignore[override]
    """Create ml_models, ml_model_outputs, and tag_model_output collections.

    Idempotent — safe to run multiple times.

    Args:
        db: ArangoDB database handle.

    """
    from arango.exceptions import CollectionCreateError, IndexCreateError

    # ------------------------------------------------------------------
    # ml_models — vertex collection, one document per ONNX head file
    # ------------------------------------------------------------------
    if not db.has_collection("ml_models"):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("ml_models")  # type: ignore[union-attr]
        logger.info("Migration V013: Created ml_models collection")
    else:
        logger.info("Migration V013: ml_models already exists — skipping creation")

    try:
        coll = db.collection("ml_models")  # type: ignore[union-attr]
        coll.add_persistent_index(fields=["path"], unique=True, sparse=False)  # type: ignore[union-attr]
        logger.info("Migration V013: Created unique persistent index on ml_models.path")
    except IndexCreateError as exc:
        if exc.http_code == 409:
            logger.info("Migration V013: ml_models.path index already exists — skipping")
        else:
            raise

    # ------------------------------------------------------------------
    # ml_model_outputs — vertex collection, one document per output dimension
    # ------------------------------------------------------------------
    if not db.has_collection("ml_model_outputs"):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("ml_model_outputs")  # type: ignore[union-attr]
        logger.info("Migration V013: Created ml_model_outputs collection")
    else:
        logger.info("Migration V013: ml_model_outputs already exists — skipping creation")

    try:
        coll = db.collection("ml_model_outputs")  # type: ignore[union-attr]
        coll.add_persistent_index(  # type: ignore[union-attr]
            fields=["model_id", "output_index"],
            unique=True,
            sparse=False,
        )
        logger.info("Migration V013: Created unique persistent index on ml_model_outputs.(model_id, output_index)")
    except IndexCreateError as exc:
        if exc.http_code == 409:
            logger.info("Migration V013: ml_model_outputs.(model_id, output_index) index already exists — skipping")
        else:
            raise

    # ------------------------------------------------------------------
    # tag_model_output — edge collection connecting tags to model outputs
    # ------------------------------------------------------------------
    if not db.has_collection("tag_model_output"):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("tag_model_output", edge=True)  # type: ignore[union-attr]
        logger.info("Migration V013: Created tag_model_output edge collection")
    else:
        logger.info("Migration V013: tag_model_output already exists — skipping creation")

    try:
        coll = db.collection("tag_model_output")  # type: ignore[union-attr]
        coll.add_persistent_index(fields=["_to"], unique=False, sparse=False)  # type: ignore[union-attr]
        logger.info("Migration V013: Created persistent index on tag_model_output._to")
    except IndexCreateError as exc:
        if exc.http_code == 409:
            logger.info("Migration V013: tag_model_output._to index already exists — skipping")
        else:
            raise

    logger.info("Migration V013: Complete")
