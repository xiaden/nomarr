"""ArangoDB schema bootstrap component.

Schema initialization (collections, indexes, graphs) - separated from persistence layer.
All operations are idempotent (safe to run multiple times).

ARCHITECTURAL NOTE:
This component lives in components/platform, NOT persistence/.
Rationale: Schema bootstrap may evolve to include non-DB setup (directories, default configs).
Persistence layer is "AQL only" - no upward dependencies.
"""

import contextlib
import logging
import os
import time

from arango import ArangoClient
from arango.exceptions import CollectionCreateError, DocumentInsertError, GraphCreateError, IndexCreateError

from nomarr.persistence.arango_client import DatabaseLike
from nomarr.persistence.database.libraries_aql import list_all_library_keys

logger = logging.getLogger(__name__)


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


def ensure_schema(db: DatabaseLike, *, models_dir: str | None = None) -> None:
    """Ensure all collections, indexes, and graphs exist (frozen baseline).

    This is a **frozen baseline** representing the schema at the last
    consolidation point.  It is idempotent and safe to call on every startup,
    but it must NOT be edited when writing new migrations.

    New schema changes go in a migration file only.  This function is updated
    only during consolidation (see ``scripts/consolidate_migrations.py``).

    Args:
        db: ArangoDB database handle
        models_dir: Path to ML models directory. When provided, creates
            per-backbone ``vectors_track_hot__*`` collections.

    """
    _create_collections(db)
    _create_indexes(db)
    _create_graphs(db)
    _validate_no_legacy_calibration(db)
    if models_dir:
        _create_vectors_track_collections(db, models_dir)


def _create_collections(db: DatabaseLike) -> None:
    """Create document and edge collections."""
    # Document collections
    document_collections = [
        "meta",
        "libraries",
        "library_files",
        "library_folders",
        "tags",  # Unified tag vertex collection (rel, value)
        "sessions",
        "calibration_state",
        "calibration_history",
        "health",
        "worker_claims",  # Discovery worker claims (Phase 2)
        # ML capacity probe collections (GPU/CPU adaptive resource management)
        "ml_capacity_estimates",  # Stores probe results per model_set_hash
        "locks",  # Unified lock system (capacity_probe, vector_promotion, etc.)
        "worker_restart_policy",  # Worker restart state persistence
        # Segment-level ML statistics (per-label aggregates from head predictions)
        "segment_scores_stats",
        # Future: "segment_scores_blob" -- full segment x class matrix for re-pooling
        # Migration tracking (database migration system)
        "applied_migrations",
        # VRAM promise registry (fleet-aware per-model GPU placement coordination)
        "vram_promises",
        # ML model registry and output activations
        "ml_models",
        "ml_model_outputs",
        # File state vertices (edge targets for file_has_state)
        "file_states",
        # Navidrome graph model — track identity and user play counts
        "navidrome_tracks",
        "navidrome_playcounts",
    ]

    for collection_name in document_collections:
        if not db.has_collection(collection_name):
            with contextlib.suppress(CollectionCreateError):
                # Collection already exists (race condition)
                db.create_collection(collection_name)

    # Edge collections
    edge_collections = [
        "song_has_tags",  # song→tag relationships (unified)
        "tag_model_output",  # tag→ml_model_output edges
        "file_has_state",  # library_files→file_states state edges
        "has_nd_id",  # navidrome_tracks→library_files file resolution
        "has_plays",  # navidrome_playcounts→navidrome_tracks play data
    ]

    for edge_collection_name in edge_collections:
        if not db.has_collection(edge_collection_name):
            with contextlib.suppress(CollectionCreateError):
                # Collection already exists (race condition)
                db.create_collection(edge_collection_name, edge=True)

    # Seed file_states vertex documents (fixed set of state targets)
    _seed_file_states(db)


def _seed_file_states(db: DatabaseLike) -> None:
    """Ensure all 16 file_states vertex documents exist (8 axes x positive + negative).

    Idempotent — inserts only if the document is missing.
    """
    from nomarr.persistence.database.file_states_aql import ALL_STATE_VERTICES

    coll = db.collection("file_states")  # type: ignore[union-attr]
    for vertex in ALL_STATE_VERTICES:
        with contextlib.suppress(DocumentInsertError):
            coll.insert({"_key": vertex.split("/")[1]})  # type: ignore[union-attr]


def _create_indexes(db: DatabaseLike) -> None:
    """Create indexes for performance.

    Idempotent - skips existing indexes.
    """
    # worker_claims indexes (discovery workers)
    _ensure_index(db, "worker_claims", "persistent", ["file_key"])
    _ensure_index(db, "worker_claims", "persistent", ["worker_id"])
    _ensure_index(db, "worker_claims", "persistent", ["claimed_at"])

    # library_files indexes
    _ensure_index(db, "library_files", "persistent", ["library_id"])
    _ensure_index(db, "library_files", "persistent", ["library_id", "path"], unique=True)
    _ensure_index(db, "library_files", "persistent", ["library_id", "normalized_path"], unique=True)
    _ensure_index(db, "library_files", "persistent", ["normalized_path"])  # Normalized path lookups
    _ensure_index(
        db,
        "library_files",
        "persistent",
        ["chromaprint"],
        sparse=True,  # Only index non-null values
    )
    # Worker queue queries (HIGH PRIORITY)
    _ensure_index(
        db,
        "library_files",
        "persistent",
        ["needs_tagging", "is_valid"],  # Worker queue filtering
    )
    _ensure_index(
        db,
        "library_files",
        "persistent",
        ["library_id", "tagged"],  # Per-library stats
    )
    _ensure_index(db, "library_files", "persistent", ["path"])  # Path lookups
    # Recalibration and tag writing (MEDIUM PRIORITY)
    _ensure_index(db, "library_files", "persistent", ["calibration_hash"])
    _ensure_index(
        db,
        "library_files",
        "persistent",
        ["write_claimed_by"],
        sparse=True,  # Only index non-null claims
    )

    # library_folders indexes
    _ensure_index(db, "library_folders", "persistent", ["library_id"])
    _ensure_index(db, "library_folders", "persistent", ["library_id", "path"], unique=True)

    # sessions TTL index (auto-expire based on expiry_timestamp)
    _ensure_index(
        db,
        "sessions",
        "ttl",
        ["expiry_timestamp"],
        expireAfter=0,  # Expire immediately when timestamp passes
    )
    # Session lookup indexes (HIGH PRIORITY)
    _ensure_index(db, "sessions", "persistent", ["session_id"])

    # health indexes (HIGH PRIORITY)
    _ensure_index(db, "health", "persistent", ["component_id"])

    # meta indexes (HIGH PRIORITY)
    _ensure_index(db, "meta", "persistent", ["key"])

    # libraries indexes (MEDIUM PRIORITY)
    _ensure_index(db, "libraries", "persistent", ["is_enabled"])

    # worker_restart_policy indexes (MEDIUM PRIORITY)
    _ensure_index(db, "worker_restart_policy", "persistent", ["component_id"])

    # calibration_state indexes (NEW - histogram-based calibration)
    _ensure_index(db, "calibration_state", "persistent", ["calibration_def_hash"], unique=True, sparse=False)
    _ensure_index(db, "calibration_state", "persistent", ["updated_at"], unique=False, sparse=False)

    # calibration_history indexes (NEW - optional drift tracking)
    _ensure_index(db, "calibration_history", "persistent", ["calibration_key"], unique=False, sparse=False)
    _ensure_index(db, "calibration_history", "persistent", ["snapshot_at"], unique=False, sparse=False)

    # file_has_state indexes (edge-based file state management)
    _ensure_index(db, "file_has_state", "persistent", ["_from", "_to"], unique=True)
    _ensure_index(db, "file_has_state", "persistent", ["_to"])

    # ─────────────────────────────────────────────────────────────────────
    # Unified tag schema indexes (TAG_UNIFICATION_REFACTOR)
    # ─────────────────────────────────────────────────────────────────────

    # tags collection: filter by rel (browse), unique on (rel, value)
    _ensure_index(
        db,
        "tags",
        "persistent",
        ["rel"],  # Browse by type, Nomarr prefix filtering
        unique=False,
        sparse=False,
    )
    _ensure_index(
        db,
        "tags",
        "persistent",
        ["rel", "value"],  # Upsert deduplication
        unique=True,
        sparse=False,
    )

    # song_has_tags: song→tag edges (minimal shape: _from, _to only)
    _ensure_index(
        db,
        "song_has_tags",
        "persistent",
        ["_from"],  # Get all tags for a song
        unique=False,
        sparse=False,
    )
    _ensure_index(
        db,
        "song_has_tags",
        "persistent",
        ["_to"],  # Get all songs for a tag
        unique=False,
        sparse=False,
    )
    _ensure_index(
        db,
        "song_has_tags",
        "persistent",
        ["_from", "_to"],  # Prevent duplicate edges (idempotent inserts)
        unique=True,
        sparse=False,
    )

    # ML model graph indexes (introduced by V014)
    _ensure_index(db, "ml_models", "persistent", ["path"], unique=True)
    _ensure_index(db, "ml_model_outputs", "persistent", ["model_id", "output_index"], unique=True)

    # tag_model_output: tag→ml_model_output edges (bidirectional traversal)
    _ensure_index(db, "tag_model_output", "persistent", ["_from"])
    _ensure_index(db, "tag_model_output", "persistent", ["_to"])
    _ensure_index(db, "tag_model_output", "persistent", ["_from", "_to"], unique=True)

    # segment_scores_stats indexes (per-label segment statistics)
    _ensure_index(db, "segment_scores_stats", "persistent", ["file_id"])
    _ensure_index(db, "segment_scores_stats", "persistent", ["head_name"])
    _ensure_index(db, "segment_scores_stats", "persistent", ["tagger_version"])
    _ensure_index(
        db,
        "segment_scores_stats",
        "persistent",
        ["file_id", "head_name", "tagger_version"],
        unique=True,
    )

    # Note: V010 added a TTL index on vram_promises.last_seen_ms, but V011 dropped it
    # (the ms vs s unit mismatch made it non-functional, and explicit owner-driven
    # cleanup via release_worker_promises() replaced it). No TTL index here.

    # ─────────────────────────────────────────────────────────────────────
    # Navidrome graph model indexes
    # ─────────────────────────────────────────────────────────────────────

    # has_nd_id: unique edge (one file per track), reverse lookup by _to
    _ensure_index(db, "has_nd_id", "persistent", ["_from", "_to"], unique=True)
    _ensure_index(db, "has_nd_id", "persistent", ["_to"])

    # navidrome_playcounts: compound index for fast sorted queries by user
    _ensure_index(db, "navidrome_playcounts", "persistent", ["userid", "playcount"])

    # has_plays: unique edge per (track, bucket), reverse lookup by _to for INBOUND traversal
    _ensure_index(db, "has_plays", "persistent", ["_from", "_to"], unique=True)
    _ensure_index(db, "has_plays", "persistent", ["_to"])


def _ensure_index(
    db: DatabaseLike,
    collection: str,
    index_type: str,
    fields: list[str],
    unique: bool = False,
    sparse: bool = False,
    expireAfter: int | None = None,  # noqa: N803
) -> None:
    """Create index if it doesn't exist.

    Args:
        db: Database handle
        collection: Collection name
        index_type: Index type ("persistent", "ttl", "hash", etc.)
        fields: Fields to index
        unique: Whether index is unique
        sparse: Whether to only index non-null values
        expireAfter: TTL expiration seconds (for ttl indexes)

    """
    try:
        coll = db.collection(collection)

        if index_type == "ttl":
            # TTL indexes use a different method
            expiry_time = expireAfter if expireAfter is not None else 0
            coll.add_ttl_index(fields=fields, expiry_time=expiry_time)
        else:
            # Persistent, hash, etc.
            coll.add_persistent_index(fields=fields, unique=unique, sparse=sparse)
    except IndexCreateError as exc:
        # 409 (HTTP Conflict) means the index already exists — safe to ignore.
        # Any other error code indicates a genuine failure (wrong field type,
        # missing collection, etc.) that should surface immediately.
        if exc.http_code != 409:
            raise


def _create_graphs(db: DatabaseLike) -> None:
    """Create named graphs for traversals.

    Creates "tag_graph" for song→tag relationships.
    """
    graph_name = "tag_graph"

    if not db.has_graph(graph_name):
        with contextlib.suppress(GraphCreateError):
            # Graph already exists (race condition)
            db.create_graph(
                name=graph_name,
                edge_definitions=[
                    {
                        "edge_collection": "song_has_tags",
                        "from_vertex_collections": ["library_files"],
                        "to_vertex_collections": ["tags"],
                    },
                ],
            )

    # Navidrome graph: play traversal path
    # tracks →[has_plays]→ playcount buckets; tracks →[has_nd_id]→ library_files
    nd_graph = "navidrome_graph"

    if not db.has_graph(nd_graph):
        with contextlib.suppress(GraphCreateError):
            db.create_graph(
                name=nd_graph,
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


def _validate_no_legacy_calibration(db: DatabaseLike) -> None:
    """Warn if legacy calibration collections exist.

    Legacy queue-based calibration was replaced by histogram-based approach.
    These collections are no longer used and can be dropped.
    """
    legacy_collections = ["calibration_queue", "calibration_runs"]
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
        from nomarr.components.ml.onnx.ml_discovery_comp import discover_heads_no_db

        heads = discover_heads_no_db(models_dir)
        backbones = sorted({h.backbone for h in heads})
        logger.debug("[bootstrap] Discovered backbones for vectors_track: %s", backbones)
        return backbones
    except Exception:
        logger.warning("[bootstrap] Could not discover backbones from %s — skipping vectors_track", models_dir)
        return []


def provision_vectors_track_for_library(db: DatabaseLike, models_dir: str, library_key: str) -> None:
    """Provision vectors_track collections for a single library.

    Creates ``vectors_track_hot__{backbone}__{library_key}`` for every
    discovered backbone. Safe to call at runtime when a new library is created.
    Idempotent — skips existing collections.

    Args:
        db: Database handle
        models_dir: Path to ML models directory
        library_key: Key of the library to provision collections for (e.g. "music")

    """
    try:
        from nomarr.components.ml.onnx.ml_discovery_comp import discover_backbones

        backbones = discover_backbones(models_dir)
    except Exception:
        logger.warning(
            "[bootstrap] Could not discover backbones from %s — skipping vectors_track provisioning",
            models_dir,
        )
        return

    if not backbones:
        logger.debug("[bootstrap] No backbones discovered in %s — skipping vectors_track provisioning", models_dir)
        return

    for backbone in backbones:
        collection_name = f"vectors_track_hot__{backbone}__{library_key}"
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


def _create_vectors_track_collections(db: DatabaseLike, models_dir: str) -> None:
    """Create per-library ``vectors_track_hot__{backbone}__{library_key}`` collections.

    For each (backbone, library_key) combination discovered from the models
    directory and the ``libraries`` collection, creates a hot collection with
    persistent indexes on ``_key`` (unique) and ``file_id``.

    Hot collections must never have vector indexes. Use
    ``promote_and_rebuild_workflow`` to create cold indexes after ML
    processing completes.

    Idempotent — skips existing collections.
    """
    # Guard: libraries collection may not exist on first-ever startup
    if not db.has_collection("libraries"):  # type: ignore[union-attr]
        logger.info("[bootstrap] No libraries collection — skipping per-library vector collections")
        return

    library_keys = list_all_library_keys(db)
    if not library_keys:
        logger.info("[bootstrap] No libraries found — skipping per-library vector collections")
        return

    for library_key in library_keys:
        provision_vectors_track_for_library(db, models_dir, library_key)
