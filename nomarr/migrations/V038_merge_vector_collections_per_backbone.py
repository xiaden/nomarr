"""V038: Merge per-library vector collections into per-backbone collections.

This forward-only migration merges all per-library vector collections
(vectors_track_hot__{backbone}__{library_key} and
vectors_track_cold__{backbone}__{library_key}) into per-backbone
collections (vectors_track_hot__{backbone} and
vectors_track_cold__{backbone}).

Steps:
1. Discover existing per-library collections, grouped by backbone.
2. Create per-backbone target collections with persistent indexes.
3. Merge hot collections: move docs + re-point file_has_vectors edges.
4. Merge cold collections: same pattern as hot.
5. Rebuild HNSW vector indexes on merged cold collections.
6. Drop empty source collections.

No rollback path (consistent with project policy for alpha software).

Key invariants:
- _key is deterministic ({file_id}_{model_suite_hash}), no collisions.
- file_has_vectors edge _to pointers are updated to new collection names.
- HNSW indexes are rebuilt on merged data, not per-library subsets.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.38"
DESCRIPTION: str = "Merge per-library vector collections into per-backbone collections"

HOT_PREFIX = "vectors_track_hot__"
COLD_PREFIX = "vectors_track_cold__"
VECTOR_EDGE_COLLECTION = "file_has_vectors"
VECTOR_GROUP_SIZE = 15  # global default (no per-library override post-refactor)


def _discover_collections(
    db: DatabaseLike,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Discover per-library vector collections, grouped by backbone.

    Iterates all ArangoDB collections, finds those matching the old
    per-library naming pattern, and groups them by backbone.

    Returns:
        (hot_by_backbone, cold_by_backbone) — dicts mapping backbone_id
        to list of source collection names.
    """
    hot_by_backbone: dict[str, list[str]] = {}
    cold_by_backbone: dict[str, list[str]] = {}

    for coll in db.collections():  # type: ignore[union-attr]
        name: str = coll["name"]

        # Match vectors_track_hot__{backbone}__{library_key}
        if name.startswith(HOT_PREFIX):
            parts = name.split("__")
            if len(parts) == 3:
                backbone = parts[1]
                hot_by_backbone.setdefault(backbone, []).append(name)

        # Match vectors_track_cold__{backbone}__{library_key}
        elif name.startswith(COLD_PREFIX):
            parts = name.split("__")
            if len(parts) == 3:
                backbone = parts[1]
                cold_by_backbone.setdefault(backbone, []).append(name)

    return hot_by_backbone, cold_by_backbone


def _ensure_target_collection(db: DatabaseLike, name: str) -> None:
    """Create a vector collection with persistent indexes if it doesn't exist."""
    if db.has_collection(name):  # type: ignore[union-attr]
        logger.info("[V038] Target collection %s already exists, skipping creation", name)
        return

    # Create the collection (no edge definition — vector collections are document collections)
    db.create_collection(name)  # type: ignore[union-attr]
    logger.info("[V038] Created target collection %s", name)

    # Add persistent indexes for lookup performance
    col = cast("Any", db.collection(name))  # type: ignore[union-attr]
    col.add_hash_index(fields=["_key"], unique=True)
    col.add_hash_index(fields=["file_id"])
    logger.info("[V038] Added indexes to %s", name)


def _merge_source_into_target(
    db: DatabaseLike,
    source_name: str,
    target_name: str,
) -> int:
    """Move all documents from source to target and re-point edges.

    Replicates VectorCollection.move_collection() logic using direct AQL
    to avoid SafeDatabase/StandardDatabase wrapping in the migration context.

    Steps:
    1. UPSERT all source documents into target (safe: deterministic _key).
    2. Re-point file_has_vectors edges from source → target.
    3. Truncate source collection.

    Returns:
        Number of documents moved.
    """
    if not db.has_collection(source_name):  # type: ignore[union-attr]
        logger.info("[V038] Source %s doesn't exist, skipping", source_name)
        return 0

    source_col = cast("Any", db.collection(source_name))  # type: ignore[union-attr]
    count = cast("int", source_col.count())
    if count == 0:
        logger.info("[V038] Source %s is empty, skipping", source_name)
        return 0

    source_prefix = f"{source_name}/"
    dest_prefix = f"{target_name}/"

    # Step 1: UPSERT all docs from source into target
    # _key is deterministic ({file_id}_{model_suite_hash}), so UPSERT
    # is safe — no collisions possible with globally unique file_ids.
    db.aql.execute(  # type: ignore[union-attr]
        "FOR doc IN @@source UPSERT { _key: doc._key } INSERT doc UPDATE doc IN @@dest OPTIONS { ignoreErrors: true }",
        bind_vars={"@source": source_name, "@dest": target_name},
    )

    # Step 2: Re-point file_has_vectors edges from source → target
    # Create new edges pointing to the dest collection, then remove
    # the old edges.  ignoreErrors skips any duplicate _from+_to pairs.
    db.aql.execute(  # type: ignore[union-attr]
        """
        LET src_edges = (
            FOR edge IN @@edge_col
                FILTER STARTS_WITH(edge._to, @source_prefix)
                RETURN edge
        )
        FOR edge IN src_edges
            LET new_to = CONCAT(@dest_prefix, PARSE_IDENTIFIER(edge._to).key)
            INSERT { _from: edge._from, _to: new_to } INTO @@edge_col OPTIONS { ignoreErrors: true }
        FOR rem_edge IN src_edges
            REMOVE rem_edge IN @@edge_col OPTIONS { ignoreErrors: true }
        """,
        bind_vars={
            "@edge_col": VECTOR_EDGE_COLLECTION,
            "source_prefix": source_prefix,
            "dest_prefix": dest_prefix,
        },
    )

    # Step 3: Truncate source (it's now empty or will be on next iteration)
    source_col.truncate()

    logger.info("[V038] Merged %s docs from %s into %s", count, source_name, target_name)
    return count


def _drop_cold_index(db: DatabaseLike, cold_name: str) -> None:
    """Drop the vector (HNSW) index on a cold collection if one exists."""
    if not db.has_collection(cold_name):  # type: ignore[union-attr]
        return
    cold_col = cast("Any", db.collection(cold_name))  # type: ignore[union-attr]
    for idx in cast("list[dict[str, Any]]", cold_col.indexes()):
        if idx.get("type") == "vector" and idx.get("id"):
            cold_col.delete_index(idx["id"])
            logger.info("[V038] Dropped vector index %s on %s", idx["id"], cold_name)


def _build_cold_index(db: DatabaseLike, cold_name: str, embed_dim: int, nlists: int) -> None:
    """Build a vector (HNSW) index on a cold collection.

    Uses the same index spec as VectorsAqlOperations._build_cold_index:
    - type: "vector" (ArangoDB's HNSW-based vector index)
    - fields: ["vector_n"] (L2-normalized vector)
    - metric: cosine
    - storedValues: ["genres"] (for efficient post-filter queries)
    """
    if not db.has_collection(cold_name):  # type: ignore[union-attr]
        msg = f"Cold collection '{cold_name}' does not exist"
        raise ValueError(msg)
    cold_col = cast("Any", db.collection(cold_name))  # type: ignore[union-attr]
    cold_col.add_index(
        {
            "type": "vector",
            "fields": ["vector_n"],
            "params": {"metric": "cosine", "dimension": embed_dim, "nLists": nlists},
            "storedValues": ["genres"],
        },
    )
    logger.info("[V038] Built vector index on %s (dim=%s, nlists=%s)", cold_name, embed_dim, nlists)


def _rebuild_hnsw_indexes(db: DatabaseLike, backbones: set[str]) -> None:
    """Rebuild HNSW indexes on merged cold collections.

    For each backbone's cold collection:
    1. Determine embed_dim from the first document.
    2. Drop any existing vector index.
    3. Compute nlists from total document count using global VECTOR_GROUP_SIZE.
    4. Build new vector index with correct embed_dim and nlists.
    """
    for backbone in sorted(backbones):
        cold_name = f"{COLD_PREFIX}{backbone}"

        if not db.has_collection(cold_name):  # type: ignore[union-attr]
            logger.info("[V038] Cold collection %s doesn't exist, skipping index rebuild", cold_name)
            continue

        # Count documents in merged cold collection
        result_cursor = db.aql.execute(  # type: ignore[union-attr]
            "RETURN LENGTH(@@cold_name)",
            bind_vars={"@cold_name": cold_name},
        )
        doc_count = 0
        for row in result_cursor:  # type: ignore[union-attr]
            doc_count = row
            break

        if doc_count == 0:
            logger.info("[V038] Cold collection %s is empty, skipping index rebuild", cold_name)
            continue

        # Read embed_dim from first document
        dim_cursor = db.aql.execute(  # type: ignore[union-attr]
            "FOR doc IN @@cold_name LIMIT 1 RETURN doc.embed_dim",
            bind_vars={"@cold_name": cold_name},
        )
        embed_dim = None
        for row in dim_cursor:  # type: ignore[union-attr]
            embed_dim = row
            break
        if embed_dim is None:
            logger.info(
                "[V038] Cannot determine embed_dim for %s, skipping index rebuild",
                cold_name,
            )
            continue

        # Drop existing vector index
        _drop_cold_index(db, cold_name)

        # Compute nlists from merged doc count using global vector_group_size
        from nomarr.helpers.vector_params_helper import compute_nlists

        nlists = compute_nlists(doc_count, VECTOR_GROUP_SIZE)
        _build_cold_index(db, cold_name, embed_dim, nlists)


def _drop_source_collections(db: DatabaseLike, collection_names: list[str]) -> None:
    """Drop a list of collections (skip if already absent)."""
    for name in collection_names:
        if db.has_collection(name):  # type: ignore[union-attr]
            db.delete_collection(name)  # type: ignore[union-attr]
            logger.info("[V038] Dropped source collection %s", name)
        else:
            logger.info("[V038] Source collection %s already absent, skipping", name)


def upgrade(db: DatabaseLike) -> None:
    """Merge per-library vector collections into per-backbone collections.

    Steps:
    1. Discover existing per-library vector collections.
    2. Create per-backbone target collections with indexes.
    3. Merge hot collections into per-backbone hot collections.
    4. Merge cold collections into per-backbone cold collections.
    5. Rebuild HNSW indexes on merged cold collections.
    6. Drop empty per-library source collections.
    """
    logger.info("[V038] Starting migration: merge per-library → per-backbone vector collections")

    # Step 1: Discover existing per-library collections
    logger.info("[V038] Step 1: Discovering existing per-library collections")
    hot_by_backbone, cold_by_backbone = _discover_collections(db)

    total_hot = sum(len(v) for v in hot_by_backbone.values())
    total_cold = sum(len(v) for v in cold_by_backbone.values())
    backbones = set(hot_by_backbone.keys()) | set(cold_by_backbone.keys())

    if not backbones:
        logger.info("[V038] No per-library vector collections found, nothing to migrate")
        return

    logger.info(
        "[V038] Found %s backbones, %s hot collections, %s cold collections",
        len(backbones),
        total_hot,
        total_cold,
    )

    # Step 2: Create per-backbone target collections
    logger.info("[V038] Step 2: Creating per-backbone target collections")
    for backbone in sorted(backbones):
        _ensure_target_collection(db, f"{HOT_PREFIX}{backbone}")
        _ensure_target_collection(db, f"{COLD_PREFIX}{backbone}")

    # Step 3: Merge hot collections
    logger.info("[V038] Step 3: Merging hot collections")
    for backbone in sorted(hot_by_backbone):
        target = f"{HOT_PREFIX}{backbone}"
        for src in hot_by_backbone[backbone]:
            _merge_source_into_target(db, src, target)

    # Step 4: Merge cold collections
    logger.info("[V038] Step 4: Merging cold collections")
    for backbone in sorted(cold_by_backbone):
        target = f"{COLD_PREFIX}{backbone}"
        for src in cold_by_backbone[backbone]:
            _merge_source_into_target(db, src, target)

    # Step 5: Rebuild HNSW indexes on merged cold collections
    logger.info("[V038] Step 5: Rebuilding HNSW indexes on merged cold collections")
    _rebuild_hnsw_indexes(db, backbones)

    # Step 6: Drop empty source collections
    logger.info("[V038] Step 6: Dropping empty source collections")
    all_sources: list[str] = []
    for sources in hot_by_backbone.values():
        all_sources.extend(sources)
    for sources in cold_by_backbone.values():
        all_sources.extend(sources)
    _drop_source_collections(db, all_sources)

    logger.info(
        "[V038] Migration complete: merged %s collections into %s backbones",
        total_hot + total_cold,
        len(backbones),
    )
