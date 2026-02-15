"""V007: Split vectors_track into hot/cold collections.

Converts existing single vectors_track__{backbone} collections to hot/cold pairs:
- Rename vectors_track__{backbone} → vectors_track_cold__{backbone}
- Create new empty vectors_track_hot__{backbone} collections
- Create persistent indexes on _key (unique) and file_id for both hot and cold

This migration supports the hot/cold architecture where:
- Hot collections: write-only, no vector indexes (no OOM during ML processing)
- Cold collections: read/search with vector indexes (promote & rebuild workflow)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 6
SCHEMA_VERSION_AFTER: int = 7
DESCRIPTION: str = "Split vectors_track collections into hot (write) and cold (read/search) pairs"

_VECTORS_TRACK_PREFIX = "vectors_track__"
_VECTORS_TRACK_HOT_PREFIX = "vectors_track_hot__"
_VECTORS_TRACK_COLD_PREFIX = "vectors_track_cold__"


def upgrade(db: DatabaseLike) -> None:
    """Convert existing vectors_track collections to hot/cold architecture.

    Steps:
    1. Discover all existing vectors_track__{backbone} collections
    2. Rename each to vectors_track_cold__{backbone} (preserve existing data + indexes)
    3. Create new empty vectors_track_hot__{backbone} collections
    4. Create persistent indexes on _key (unique) and file_id for both hot and cold

    Args:
        db: ArangoDB database handle.

    """
    collections = db.collections()  # type: ignore[union-attr]
    if collections is None:
        logger.warning(
            "Migration V007: Could not list collections. "
            "Skipping hot/cold split."
        )
        return

    # Step 1: Discover existing vectors_track collections
    vt_collections = [
        c["name"]
        for c in collections  # type: ignore[union-attr]
        if c["name"].startswith(_VECTORS_TRACK_PREFIX)
        and not c["name"].startswith(_VECTORS_TRACK_HOT_PREFIX)
        and not c["name"].startswith(_VECTORS_TRACK_COLD_PREFIX)
    ]

    if not vt_collections:
        logger.info(
            "Migration V007: No vectors_track collections found. "
            "Nothing to migrate."
        )
        return

    logger.info(
        "Migration V007: Found %d vectors_track collection(s) to migrate: %s",
        len(vt_collections),
        ", ".join(sorted(vt_collections)),
    )

    # Collect existing hot/cold collection names for idempotency checks
    existing_names = {c["name"] for c in collections}  # type: ignore[union-attr]

    # Process each collection
    for old_name in sorted(vt_collections):
        # Extract backbone_id from collection name
        # "vectors_track__effnet" → "effnet"
        backbone_id = old_name[len(_VECTORS_TRACK_PREFIX) :]
        hot_name = f"{_VECTORS_TRACK_HOT_PREFIX}{backbone_id}"
        cold_name = f"{_VECTORS_TRACK_COLD_PREFIX}{backbone_id}"

        # Step 2: Rename old collection to cold (preserves data + existing indexes)
        # Skip if cold already exists (idempotency)
        if cold_name in existing_names:
            logger.info(
                "Migration V007: Cold collection %s already exists, skipping rename",
                cold_name,
            )
        else:
            logger.info(
                "Migration V007: Renaming %s → %s (preserving %d vectors)",
                old_name,
                cold_name,
                db.collection(old_name).count(),  # type: ignore[union-attr]
            )
            db.collection(old_name).rename(cold_name)  # type: ignore[union-attr]

        # Step 3: Create new empty hot collection
        # Skip if hot already exists (idempotency)
        if hot_name in existing_names:
            logger.info(
                "Migration V007: Hot collection %s already exists, skipping create",
                hot_name,
            )
        else:
            logger.info(
                "Migration V007: Creating empty hot collection: %s",
                hot_name,
            )
            db.create_collection(hot_name)

        # Step 4: Create indexes on both hot and cold
        # Hot indexes: unique _key (enforce invariant), file_id (cascade delete performance)
        hot_coll = db.collection(hot_name)  # type: ignore[union-attr]
        hot_existing_indexes = {idx["name"] for idx in hot_coll.indexes()}  # type: ignore[union-attr]
        if "idx_hot_key_unique" not in hot_existing_indexes:
            hot_coll.add_persistent_index(  # type: ignore[union-attr]
                fields=["_key"],
                unique=True,
                name="idx_hot_key_unique",
            )
        if "idx_hot_file_id" not in hot_existing_indexes:
            hot_coll.add_persistent_index(  # type: ignore[union-attr]
                fields=["file_id"],
                unique=False,
                name="idx_hot_file_id",
            )

        # Cold indexes: unique _key, file_id (cold already has vector index from old collection)
        cold_coll = db.collection(cold_name)  # type: ignore[union-attr]
        # Check if _key index already exists (it might from old schema)
        existing_indexes = {idx["name"] for idx in cold_coll.indexes()}  # type: ignore[union-attr]
        if "idx_cold_key_unique" not in existing_indexes:
            cold_coll.add_persistent_index(  # type: ignore[union-attr]
                fields=["_key"],
                unique=True,
                name="idx_cold_key_unique",
            )
        if "idx_cold_file_id" not in existing_indexes:
            cold_coll.add_persistent_index(  # type: ignore[union-attr]
                fields=["file_id"],
                unique=False,
                name="idx_cold_file_id",
            )

        logger.info(
            "Migration V007: Completed hot/cold split for backbone: %s",
            backbone_id,
        )

    logger.info(
        "Migration V007: Successfully migrated %d backbones to hot/cold architecture.",
        len(vt_collections),
    )
