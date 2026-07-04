"""ArangoDB schema bootstrap component.

Schema initialization (collections, indexes, graphs) - separated from persistence layer.
All operations are idempotent (safe to run multiple times).

ARCHITECTURAL NOTE:
This component lives in components/platform, NOT persistence/.
Rationale: Schema bootstrap may evolve to include non-DB setup (directories, default configs).
Persistence layer is "AQL only" - no upward dependencies.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from typing import TYPE_CHECKING

from arango import ArangoClient
from arango.exceptions import CollectionCreateError, DocumentInsertError, IndexCreateError

from nomarr.components.ml.onnx.ml_discovery_comp import discover_backbones, discover_heads_no_db
from nomarr.helpers.constants.file_states import ALL_STATE_VERTICES
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.schema import CollectionNames
from nomarr.persistence.schema.ddl import DOCUMENT_COLLECTIONS, EDGE_COLLECTIONS
from nomarr.persistence.schema_types import VectorsTrackCold, VectorsTrackHot

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_VECTOR_TEMPLATE_NAMES: tuple[str, ...] = tuple(
    vector_cls.NAME_PATTERN.split("__{", maxsplit=1)[0] for vector_cls in (VectorsTrackHot, VectorsTrackCold)
)


def list_template_collection_names() -> list[str]:
    """Return template collection family names for dynamic vector collections."""
    return list(_VECTOR_TEMPLATE_NAMES)


def ensure_schema_from_database(db: Database, *, models_dir: str | None = None) -> None:
    """Bootstrap the frozen schema using the raw handle carried by ``Database``."""
    ensure_schema(db.db, models_dir=models_dir)


def register_template_collection(db: Database, collection_name: str, template_name: str) -> None:
    """Register an existing dynamic collection against its template family."""
    db.ml.add_vector_collection(collection_name, template_name)


def wait_for_arango(hosts: str, max_attempts: int = 30, delay_s: float = 2.0) -> bool:
    """Wait until ArangoDB is reachable.

    The single, canonical place to block startup until the database is up.
    Uses root credentials from ARANGO_ROOT_PASSWORD; if that env var is not
    set, the function returns True immediately (dev/test environments that
    already have the app user configured).

    Args:
        hosts: ArangoDB server URL(s)
        max_attempts: Maximum connection attempts (default 30 = 60 seconds)
        delay_s: Delay between attempts in seconds

    Returns:
        True if connected, False if timeout

    """
    root_password = os.getenv("ARANGO_ROOT_PASSWORD")
    if not root_password:
        logger.debug("ARANGO_ROOT_PASSWORD not set, skipping connection wait")
        return True
    for attempt in range(1, max_attempts + 1):
        try:
            client = ArangoClient(hosts=hosts)
            sys_db = client.db("_system", username="root", password=root_password)
            sys_db.properties()
            logger.debug("ArangoDB connection established (attempt %d/%d)", attempt, max_attempts)
            return True
        except Exception as e:
            if attempt < max_attempts:
                logger.info("Waiting for ArangoDB... (%d/%d): %s", attempt, max_attempts, e)
                time.sleep(delay_s)
            else:
                logger.exception("ArangoDB connection timeout after %d attempts: %s", max_attempts, e)
                return False
    return False


def ensure_schema(db: SafeDatabase, *, models_dir: str | None = None) -> None:
    """Ensure all collections, indexes, and graphs exist (frozen baseline).

    This is a **frozen baseline** representing the schema at the last
    consolidation point.  It is idempotent and safe to call on every startup,
    but it must NOT be edited when writing new migrations.

    New schema changes go in a migration file only.  This function is updated
    only during consolidation (see ``scripts/consolidate_migrations.py``).

    Args:
        db: ArangoDB database handle
        models_dir: Path to ML models directory. When provided, creates
            per-backbone ``vectors_track_hot__{backbone}`` collections.

    """
    _create_collections(db)
    _create_indexes(db)
    _create_graphs(db)
    _validate_no_legacy_calibration(db)
    if models_dir:
        _create_vectors_track_collections(db, models_dir)


def _create_collections(db: SafeDatabase) -> None:
    """Create document and edge collections using DDL definitions."""
    for coll_def in DOCUMENT_COLLECTIONS:
        name = coll_def.name.value
        if not db.has_collection(name):
            with contextlib.suppress(CollectionCreateError):
                db.create_collection(name)

    for coll_def in EDGE_COLLECTIONS:
        name = coll_def.name.value
        if not db.has_collection(name):
            with contextlib.suppress(CollectionCreateError):
                db.create_collection(name, edge=True)

    # Seed file_states vertex documents (fixed set of state targets)
    _seed_file_states(db)


def _seed_file_states(db: SafeDatabase) -> None:
    """Ensure all 16 file_states vertex documents exist (8 axes x positive + negative).

    Idempotent — inserts only if the document is missing.
    """
    coll = db.collection(CollectionNames.FILE_STATES.value)  # type: ignore[union-attr]
    for vertex in ALL_STATE_VERTICES:
        with contextlib.suppress(DocumentInsertError):
            coll.insert({"_key": vertex.split("/")[1]})  # type: ignore[union-attr]


def _seed_pipeline_states(db: SafeDatabase) -> None:
    """No-op: pipeline states are now fields on library documents.

    Kept for backward compatibility during migration. The old
    library_pipeline_states collection is no longer used.
    """


def seed_state_documents(db: Database) -> None:
    """Reseed all singleton state vertex documents.

    Idempotent — runs on every startup to restore any accidentally-deleted
    state documents without requiring a migration.  Both collections must
    already exist (created by ensure_schema or a migration).
    """
    _seed_file_states(db.db)
    _seed_pipeline_states(db.db)


def _create_indexes(db: SafeDatabase) -> None:
    """Create indexes from DDL definitions.

    Idempotent - skips existing indexes.
    """
    all_defs = DOCUMENT_COLLECTIONS + EDGE_COLLECTIONS
    for coll_def in all_defs:
        for idx_def in coll_def.indexes:
            _ensure_index(
                db,
                coll_def.name.value,
                idx_def.index_type,
                idx_def.fields,
                unique=idx_def.unique,
                sparse=idx_def.sparse,
                expire_after=idx_def.expire_after,
            )


def _ensure_index(
    db: SafeDatabase,
    collection: str,
    index_type: str,
    fields: list[str],
    unique: bool = False,
    sparse: bool = False,
    expire_after: int | None = None,
) -> None:
    """Create index if it doesn't exist.

    Args:
        db: Database handle
        collection: Collection name
        index_type: Index type ("persistent", "ttl", "hash", etc.)
        fields: Fields to index
        unique: Whether index is unique
        sparse: Whether to only index non-null values
        expire_after: TTL expiration seconds (for ttl indexes)

    """
    try:
        coll = db.collection(collection)

        if index_type == "ttl":
            # TTL indexes use a different method
            expiry_time = expire_after if expire_after is not None else 0
            coll.add_ttl_index(fields=fields, expiry_time=expiry_time)
        else:
            # Persistent, hash, etc.
            coll.add_persistent_index(fields=fields, unique=unique, sparse=sparse)
    except IndexCreateError as exc:
        # 409 (HTTP Conflict) means the index already exists — safe to ignore.
        # ArangoDB 3.12 may also return HTTP 400 / ERR 1210 (unique constraint
        # violated) when re-adding a unique index that already exists on the
        # same fields. Both cases are idempotent — the index is already there.
        if exc.http_code == 409:
            return
        if exc.http_code == 400 and exc.error_code == 1210:
            return
        raise


def _create_graphs(db: SafeDatabase) -> None:
    """Named graphs have been dropped (V030). No graphs are created.

    ArangoDB named graphs were removed because no AQL traversal queries used
    them — edge collections are queried directly. This stub is retained so the
    ``ensure_schema`` call-site does not need updating.
    """


def _validate_no_legacy_calibration(db: SafeDatabase) -> None:
    """Warn if legacy calibration collections exist.

    Legacy queue-based calibration was replaced by histogram-based approach.
    These collections are no longer used and can be dropped.
    """
    legacy_collections = ["calibration_queue", "calibration_runs"]  # no CollectionNames — these are truly legacy
    found_legacy = [name for name in legacy_collections if db.has_collection(name)]

    if found_legacy:
        logger.error(
            "Legacy calibration collections detected: %s. "
            "These are no longer used by histogram-based calibration. "
            "To remove them, run: python scripts/drop_old_calibration_collections.py",
            ", ".join(found_legacy),
        )


# ─────────────────────────────────────────────────────────────────────
# Vectors track: per-backbone embedding collections
# ─────────────────────────────────────────────────────────────────────


def _discover_backbone_ids(models_dir: str) -> list[str]:
    """Discover unique backbone identifiers from the models directory.

    Returns:
        Sorted list of backbone IDs (e.g., ["effnet", "musicnn", "yamnet"]).

    """
    try:
        heads = discover_heads_no_db(models_dir)
        backbones = sorted({h.backbone for h in heads})
        logger.debug("[bootstrap] Discovered backbones for vectors_track: %s", backbones)
        return backbones
    except Exception:
        logger.warning(
            "[bootstrap] Could not discover backbones from %s — skipping vectors_track", models_dir, exc_info=True
        )
        return []


def _create_vectors_track_collections(db: SafeDatabase, models_dir: str) -> None:
    """Create per-backbone ``vectors_track_hot__{backbone}`` collections.

    For each backbone discovered from the models directory, creates a hot
    collection with persistent indexes on ``_key`` (unique) and ``file_id``.

    Hot collections must never have vector indexes. Use
    ``promote_and_rebuild_workflow`` to create cold indexes after ML
    processing completes.

    Idempotent — skips existing collections.
    """
    try:
        backbones = discover_backbones(models_dir)
    except Exception:
        logger.warning(
            "[bootstrap] Could not discover backbones from %s — skipping vectors_track provisioning",
            models_dir,
            exc_info=True,
        )
        return

    if not backbones:
        logger.debug("[bootstrap] No backbones discovered in %s — skipping vectors_track provisioning", models_dir)
        return

    for backbone in backbones:
        collection_name = f"vectors_track_hot__{backbone}"
        created_collection = False

        if not db.has_collection(collection_name):  # type: ignore[union-attr]
            with contextlib.suppress(CollectionCreateError):
                db.create_collection(collection_name)  # type: ignore[union-attr]
                created_collection = True

        _ensure_index(db, collection_name, "persistent", ["_key"], unique=True)
        _ensure_index(db, collection_name, "persistent", ["file_id"])

        if created_collection:
            logger.info("[bootstrap] Created collection %s", collection_name)
        else:
            logger.info("[bootstrap] Provisioned indexes for %s", collection_name)
