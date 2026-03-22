"""V019: Navidrome graph model — create collections and migrate navidrome_song_map.

Background
----------
The flat ``navidrome_song_map`` collection is replaced by a graph model:
- ``navidrome_tracks`` (vertex): keyed by nd_id
- ``has_nd_id`` (edge): navidrome_tracks/{nd_id} → library_files/{file_key}
- ``navidrome_playcounts`` (vertex): bucketed by {playcount}:{userid}
- ``has_plays`` (edge): navidrome_tracks/{nd_id} → navidrome_playcounts/{playcount}:{userid}

The playcount model uses bucketed vertices: each vertex represents a
(playcount_value, user) pair with a compound ``[userid, playcount]`` index
for fast sorted queries.  Edge direction is tracks → buckets so INBOUND
traversal from a bucket finds all tracks with that play count.

Existing ``navidrome_song_map`` documents are migrated:
- Each doc becomes a ``navidrome_tracks`` vertex (``_key = _key``)
- Each doc becomes a ``has_nd_id`` edge (``_from = navidrome_tracks/{_key}``,
  ``_to = {file_id}``) — file_id is already a full doc ID.
- ``navidrome_playcounts`` and ``has_plays`` are left empty (populated by
  Plan B scrobble ingestion).

The ``navidrome_song_map`` collection is dropped after migration.

Forward-only; no downgrade path.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from arango.exceptions import CollectionCreateError, GraphCreateError, IndexCreateError

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 18
SCHEMA_VERSION_AFTER: int = 19
DESCRIPTION: str = "Navidrome graph model + vector promotion locks collection"

_OLD_COLLECTION = "navidrome_song_map"
_BATCH_SIZE: int = 1000


def _ensure_collection(db: DatabaseLike, name: str, *, edge: bool = False) -> None:
    """Create a collection if it does not exist."""
    if not db.has_collection(name):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection(name, edge=edge)  # type: ignore[union-attr]
            logger.info("[V019] Created %s collection %s", "edge" if edge else "document", name)


def _ensure_index(
    db: DatabaseLike,
    collection: str,
    fields: list[str],
    *,
    unique: bool = False,
) -> None:
    """Create a persistent index if it doesn't exist."""
    try:
        coll = db.collection(collection)  # type: ignore[union-attr]
        coll.add_persistent_index(fields=fields, unique=unique)  # type: ignore[union-attr]
    except IndexCreateError as exc:
        if exc.http_code != 409:
            raise


def _create_collections(db: DatabaseLike) -> None:
    """Create all new collections idempotently."""
    # Navidrome graph model
    _ensure_collection(db, "navidrome_tracks")
    _ensure_collection(db, "navidrome_playcounts")
    _ensure_collection(db, "has_nd_id", edge=True)
    _ensure_collection(db, "has_plays", edge=True)

    # Vector promotion coordination lock
    _ensure_collection(db, "vector_promotion_locks")


def _create_indexes(db: DatabaseLike) -> None:
    """Create indexes matching bootstrap conventions."""
    # has_nd_id: unique edge (one file per track), reverse lookup by _to
    _ensure_index(db, "has_nd_id", ["_from", "_to"], unique=True)
    _ensure_index(db, "has_nd_id", ["_to"])

    # navidrome_playcounts: compound index for fast sorted queries by user
    _ensure_index(db, "navidrome_playcounts", ["userid", "playcount"])

    # has_plays: unique edge per (track, bucket), reverse lookup by _to
    _ensure_index(db, "has_plays", ["_from", "_to"], unique=True)
    _ensure_index(db, "has_plays", ["_to"])


def _create_graph(db: DatabaseLike) -> None:
    """Create the navidrome_graph named graph."""
    if not db.has_graph("navidrome_graph"):  # type: ignore[union-attr]
        with contextlib.suppress(GraphCreateError):
            db.create_graph(  # type: ignore[union-attr]
                name="navidrome_graph",
                edge_definitions=[
                    {
                        "edge_collection": "has_plays",
                        "from_vertex_collections": ["navidrome_tracks"],
                        "to_vertex_collections": ["navidrome_playcounts"],
                    },
                    {
                        "edge_collection": "has_nd_id",
                        "from_vertex_collections": ["navidrome_tracks"],
                        "to_vertex_collections": ["library_files"],
                    },
                ],
            )
            logger.info("[V019] Created named graph navidrome_graph")


def _migrate_song_map(db: DatabaseLike) -> None:
    """Migrate navidrome_song_map documents into graph collections.

    Each document becomes:
    1. A ``navidrome_tracks`` vertex (``_key = doc._key``)
    2. A ``has_nd_id`` edge (``_from = navidrome_tracks/{_key}``, ``_to = doc.file_id``)

    Skips documents where ``file_id`` is null or empty.
    """
    if not db.has_collection(_OLD_COLLECTION):  # type: ignore[union-attr]
        logger.info("[V019] %s does not exist — nothing to migrate", _OLD_COLLECTION)
        return

    old_coll = db.collection(_OLD_COLLECTION)  # type: ignore[union-attr]
    doc_count = old_coll.count()  # type: ignore[union-attr]
    if doc_count == 0:  # type: ignore[operator]
        logger.info("[V019] %s is empty — nothing to migrate", _OLD_COLLECTION)
        return

    logger.info("[V019] Migrating %s documents from %s", doc_count, _OLD_COLLECTION)

    # Read all documents from old collection
    cursor = db.aql.execute(  # type: ignore[union-attr]
        f"FOR doc IN {_OLD_COLLECTION} RETURN doc",
        batch_size=_BATCH_SIZE,
    )

    track_docs: list[dict[str, str]] = []
    edge_docs: list[dict[str, str]] = []
    skipped = 0

    for row in cursor:  # type: ignore[union-attr]
        nd_id: str = row["_key"]
        file_id: str | None = row.get("file_id")

        track_docs.append({"_key": nd_id})

        if file_id:
            edge_docs.append({
                "_from": f"navidrome_tracks/{nd_id}",
                "_to": file_id,
            })
        else:
            skipped += 1

    # Batch insert track vertices
    for i in range(0, len(track_docs), _BATCH_SIZE):
        batch = track_docs[i : i + _BATCH_SIZE]
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN @batch
                UPSERT { _key: doc._key }
                INSERT doc
                UPDATE {}
                IN navidrome_tracks
            """,
            bind_vars={"batch": batch},  # type: ignore[dict-item]  # python-arango stubs don't accept list[dict]
        )

    logger.info("[V019] Inserted %d track vertices", len(track_docs))

    # Batch insert has_nd_id edges
    for i in range(0, len(edge_docs), _BATCH_SIZE):
        batch = edge_docs[i : i + _BATCH_SIZE]
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN @batch
                UPSERT { _from: doc._from, _to: doc._to }
                INSERT doc
                UPDATE {}
                IN has_nd_id
            """,
            bind_vars={"batch": batch},  # type: ignore[dict-item]  # python-arango stubs don't accept list[dict]
        )

    logger.info("[V019] Inserted %d has_nd_id edges (skipped %d with no file_id)", len(edge_docs), skipped)


def _drop_old_collection(db: DatabaseLike) -> None:
    """Drop the old navidrome_song_map collection."""
    if db.has_collection(_OLD_COLLECTION):  # type: ignore[union-attr]
        db.delete_collection(_OLD_COLLECTION)  # type: ignore[union-attr]
        logger.info("[V019] Dropped collection %s", _OLD_COLLECTION)


def upgrade(db: DatabaseLike) -> None:  # type: ignore[override]
    """Create Navidrome graph collections + vector promotion locks, migrate song_map, drop old.

    Steps:
    1. Create navidrome_tracks, navidrome_playcounts, has_nd_id, has_plays, vector_promotion_locks
    2. Create indexes on edge collections and compound vertex index
    3. Create navidrome_graph named graph
    4. Migrate navidrome_song_map docs → navidrome_tracks + has_nd_id
    5. Drop navidrome_song_map

    All operations are idempotent. Safe to re-run on partial migration.

    Args:
        db: ArangoDB database handle.
    """
    logger.info("[V019] Starting Navidrome graph model migration")

    _create_collections(db)
    _create_indexes(db)
    _create_graph(db)
    _migrate_song_map(db)
    _drop_old_collection(db)

    logger.info("[V019] Migration complete — Navidrome graph model active")
