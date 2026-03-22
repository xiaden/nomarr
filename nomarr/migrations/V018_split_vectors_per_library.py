"""V018: Split global vector collections into per-library collections.

Background
----------
Vector collections previously used a global naming scheme:
``vectors_track_{temp}__{backbone_id}`` (temp = hot|cold).

The new per-library naming scheme is:
``vectors_track_{temp}__{backbone_id}__{library_key}``

This migration finds all global vector collections (those with exactly two
segments after splitting on ``__``), resolves each document's library via
``file_id`` -> ``library_files.library_id``, and copies documents into the
correct per-library collection.  Global collections are dropped after all
documents are migrated.

Edge cases handled:
- Orphaned vectors (file_id not in library_files): logged and skipped.
- Already-existing per-library collections (partial migration): merged
  with UPSERT semantics (overwriteMode: replace).
- Empty global collections: dropped immediately.

Forward-only; no downgrade path.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 17
SCHEMA_VERSION_AFTER: int = 18
DESCRIPTION: str = "Split global vector collections into per-library collections"

# Batch size for AQL INSERT operations
_BATCH_SIZE: int = 1000


def _find_global_vector_collections(db: DatabaseLike) -> list[tuple[str, str, str]]:
    """Find global vector collections (no library_key segment).

    Returns:
        List of (collection_name, temp, backbone_id) tuples where temp is
        'hot' or 'cold'.
    """
    results: list[tuple[str, str, str]] = []
    collections: list[dict[str, Any]] = db.collections()  # type: ignore[assignment,union-attr]
    for coll in collections:
        name: str = coll["name"] if isinstance(coll, dict) else coll
        if name.startswith("_"):
            continue

        for prefix in ("vectors_track_hot__", "vectors_track_cold__"):
            if not name.startswith(prefix):
                continue
            suffix = name[len(prefix):]
            # Global collections have NO double-underscore in the suffix.
            # Per-library collections have the pattern: {backbone}__{library_key}
            if "__" in suffix:
                # Already per-library — skip
                continue
            temp = "hot" if "_hot__" in name else "cold"
            backbone_id = suffix
            results.append((name, temp, backbone_id))
    return results


def _ensure_collection(db: DatabaseLike, name: str) -> None:
    """Create a collection if it does not exist."""
    if not db.has_collection(name):  # type: ignore[union-attr]
        db.create_collection(name)  # type: ignore[union-attr]
        logger.info("[V018] Created collection %s", name)


def _ensure_indexes(db: DatabaseLike, collection_name: str) -> None:
    """Create persistent indexes matching bootstrap conventions."""
    from arango.exceptions import IndexCreateError

    coll = db.collection(collection_name)  # type: ignore[union-attr]
    try:
        coll.add_persistent_index(fields=["_key"], unique=True)  # type: ignore[union-attr]
    except IndexCreateError as exc:
        if exc.http_code != 409:
            raise
    try:
        coll.add_persistent_index(fields=["file_id"], unique=False)  # type: ignore[union-attr]
    except IndexCreateError as exc:
        if exc.http_code != 409:
            raise


def _split_collection(
    db: DatabaseLike,
    global_name: str,
    temp: str,
    backbone_id: str,
) -> None:
    """Split a single global vector collection into per-library collections.

    Groups documents by library_key (resolved via file_id -> library_files),
    batch-inserts into per-library collections, then drops the global collection.
    """
    # Count documents for logging
    global_coll = db.collection(global_name)  # type: ignore[union-attr]
    doc_count = global_coll.count()  # type: ignore[union-attr]
    if doc_count == 0:  # type: ignore[operator]
        logger.info("[V018] %s is empty — dropping", global_name)
        db.delete_collection(global_name)  # type: ignore[union-attr]
        return

    logger.info("[V018] Splitting %s (%s documents)", global_name, doc_count)

    # Step 1: Group documents by library_key via AQL join
    # library_files.library_id is like "libraries/mykey" — extract _key portion
    cursor = db.aql.execute(  # type: ignore[union-attr]
        f"""
        FOR doc IN {global_name}
            LET lf = DOCUMENT(doc.file_id)
            LET lib_key = (lf != null) ? SPLIT(lf.library_id, "/")[1] : null
            RETURN {{
                lib_key: lib_key,
                doc: UNSET(doc, "_id", "_rev")
            }}
        """,
        batch_size=_BATCH_SIZE,
    )

    # Accumulate docs by library_key; track orphans
    by_library: dict[str, list[dict]] = {}  # type: ignore[type-arg]
    orphan_count = 0
    for row in cursor:  # type: ignore[union-attr]
        lib_key = row["lib_key"]
        if lib_key is None:
            orphan_count += 1
            continue
        by_library.setdefault(lib_key, []).append(row["doc"])

    if orphan_count:
        logger.warning("[V018] %s: skipped %d orphaned vectors (file_id not in library_files)", global_name, orphan_count)

    # Step 2: Insert into per-library collections
    for library_key, docs in by_library.items():
        target_name = f"vectors_track_{temp}__{backbone_id}__{library_key}"
        _ensure_collection(db, target_name)
        _ensure_indexes(db, target_name)

        # Batch insert with overwrite to handle partial migrations
        total_inserted = 0
        for i in range(0, len(docs), _BATCH_SIZE):
            batch = docs[i : i + _BATCH_SIZE]
            db.aql.execute(  # type: ignore[union-attr]
                f"""
                FOR doc IN @batch
                    INSERT doc INTO {target_name}
                    OPTIONS {{ overwriteMode: "replace" }}
                """,
                bind_vars={"batch": batch},
            )
            total_inserted += len(batch)

        logger.info(
            "[V018] %s -> %s: inserted %d documents",
            global_name,
            target_name,
            total_inserted,
        )

    # Step 3: Drop global collection
    db.delete_collection(global_name)  # type: ignore[union-attr]
    logger.info("[V018] Dropped global collection %s", global_name)


def upgrade(db: DatabaseLike) -> None:  # type: ignore[override]
    """Split global vector collections into per-library collections.

    For each global ``vectors_track_{temp}__{backbone_id}`` collection:
    1. Join documents on file_id to library_files to resolve library_key.
    2. Batch-insert into per-library ``vectors_track_{temp}__{backbone_id}__{library_key}``.
    3. Create persistent indexes on new collections.
    4. Drop the global collection.

    Orphaned vectors (file_id not in library_files) are logged and skipped.
    Already-existing per-library collections are merged via overwriteMode replace.

    Args:
        db: ArangoDB database handle.
    """
    global_collections = _find_global_vector_collections(db)

    if not global_collections:
        logger.info("[V018] No global vector collections found — nothing to migrate")
        return

    logger.info("[V018] Found %d global vector collections to split", len(global_collections))

    for global_name, temp, backbone_id in global_collections:
        _split_collection(db, global_name, temp, backbone_id)

    logger.info("[V018] Migration complete — all global vector collections split into per-library collections")
