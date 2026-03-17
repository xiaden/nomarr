"""V015: Add navidrome_song_map collection for Navidrome-Nomarr ID mapping.

Background
----------
Navidrome and Nomarr maintain separate song inventories with different IDs.
To power features like Instant Mix (vector similarity) through the Navidrome
WASM plugin, we need a persistent bidirectional mapping between Navidrome
mediafile IDs and Nomarr library_files IDs.

This mapping is built by walking Navidrome's album inventory via the Subsonic
API and matching file paths (with configurable prefix remapping) to Nomarr's
``library_files`` collection.

Schema
------
``navidrome_song_map`` — vertex collection:

- ``_key`` (str): Navidrome mediafile ID (primary key)
- ``file_id`` (str): Nomarr document ID (e.g. ``library_files/abc123``)
- ``nd_path`` (str): Original file path as reported by Navidrome
- ``synced_at`` (int): Timestamp in milliseconds when this mapping was created/updated

Indexes:

- Unique persistent index on ``file_id`` for reverse lookups
  (Nomarr file_id → Navidrome ID)

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
SCHEMA_VERSION_BEFORE: int = 14
SCHEMA_VERSION_AFTER: int = 15
DESCRIPTION: str = "Add navidrome_song_map collection for Navidrome-Nomarr ID mapping"


def upgrade(db: DatabaseLike) -> None:  # type: ignore[override]
    """Create navidrome_song_map vertex collection with unique index on file_id.

    Idempotent — safe to run multiple times.

    Args:
        db: ArangoDB database handle.
    """
    from arango.exceptions import CollectionCreateError, IndexCreateError

    # ------------------------------------------------------------------
    # navidrome_song_map — vertex collection, one document per mapped song
    # ------------------------------------------------------------------
    if not db.has_collection("navidrome_song_map"):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("navidrome_song_map")  # type: ignore[union-attr]
        logger.info("Migration V015: Created navidrome_song_map collection")
    else:
        logger.info("Migration V015: navidrome_song_map already exists — skipping creation")

    try:
        coll = db.collection("navidrome_song_map")  # type: ignore[union-attr]
        coll.add_persistent_index(fields=["file_id"], unique=True, sparse=False)  # type: ignore[union-attr]
        logger.info("Migration V015: Created unique persistent index on navidrome_song_map.file_id")
    except IndexCreateError as exc:
        if exc.http_code == 409:
            logger.info("Migration V015: navidrome_song_map.file_id index already exists — skipping")
        else:
            raise

    logger.info("Migration V015: Complete")
