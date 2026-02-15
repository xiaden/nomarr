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

from arango.exceptions import CollectionCreateError, GraphCreateError, IndexCreateError

from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)


def ensure_schema(db: DatabaseLike, *, models_dir: str | None = None) -> None:
    """Ensure all collections, indexes, and graphs exist.

    Idempotent - safe to call on every startup.
    Creates missing collections/indexes but does NOT alter existing ones.

    Args:
        db: ArangoDB database handle
        models_dir: Path to ML models directory. When provided, creates
            per-backbone ``vectors_track__*`` collections and indexes.

    """
    _create_collections(db)
    _create_indexes(db)
    _create_graphs(db)
    _validate_no_legacy_calibration(db)
    if models_dir:
        _create_vectors_track_collections(db, models_dir)
        _create_vectors_track_indexes(db, models_dir)


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
        "ml_capacity_probe_locks",  # Prevents concurrent probes
        "worker_restart_policy",  # Worker restart state persistence
        # Segment-level ML statistics (per-label aggregates from head predictions)
        "segment_scores_stats",
        # Future: "segment_scores_blob" -- full segment x class matrix for re-pooling
        # Migration tracking (database migration system)
        "applied_migrations",
    ]

    for collection_name in document_collections:
        if not db.has_collection(collection_name):
            with contextlib.suppress(CollectionCreateError):
                # Collection already exists (race condition)
                db.create_collection(collection_name)

    # Edge collections
    edge_collections = [
        "song_tag_edges",  # song→tag relationships (unified)
    ]

    for edge_collection_name in edge_collections:
        if not db.has_collection(edge_collection_name):
            with contextlib.suppress(CollectionCreateError):
                # Collection already exists (race condition)
                db.create_collection(edge_collection_name, edge=True)


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

    # song_tag_edges: song→tag edges (minimal shape: _from, _to only)
    _ensure_index(
        db,
        "song_tag_edges",
        "persistent",
        ["_from"],  # Get all tags for a song
        unique=False,
        sparse=False,
    )
    _ensure_index(
        db,
        "song_tag_edges",
        "persistent",
        ["_to"],  # Get all songs for a tag
        unique=False,
        sparse=False,
    )
    _ensure_index(
        db,
        "song_tag_edges",
        "persistent",
        ["_from", "_to"],  # Prevent duplicate edges (idempotent inserts)
        unique=True,
        sparse=False,
    )

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
    except IndexCreateError:
        pass  # Index already exists  # Index already exists  # Index already exists  # Index already exists  # Index already exists  # Index already exists


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
                        "edge_collection": "song_tag_edges",
                        "from_vertex_collections": ["library_files"],
                        "to_vertex_collections": ["tags"],
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
        from nomarr.components.ml.ml_discovery_comp import discover_heads

        heads = discover_heads(models_dir)
        backbones = sorted({h.backbone for h in heads})
        logger.info("[bootstrap] Discovered backbones for vectors_track: %s", backbones)
        return backbones
    except Exception:
        logger.warning("[bootstrap] Could not discover backbones from %s — skipping vectors_track", models_dir)
        return []


def _create_vectors_track_collections(db: DatabaseLike, models_dir: str) -> None:
    """Create a ``vectors_track__{backbone}`` collection per discovered backbone.

    Idempotent — skips existing collections.
    """
    for backbone in _discover_backbone_ids(models_dir):
        collection_name = f"vectors_track__{backbone}"
        if not db.has_collection(collection_name):
            with contextlib.suppress(CollectionCreateError):
                db.create_collection(collection_name)
                logger.info("[bootstrap] Created collection %s", collection_name)

        # Persistent index on file_id for cascade delete performance
        _ensure_index(db, collection_name, "persistent", ["file_id"])


def _create_vectors_track_indexes(db: DatabaseLike, models_dir: str) -> None:
    """Create vector indexes on ``vectors_track__{backbone}`` collections.

    Vector indexes require a fixed ``dimension`` parameter that matches the
    backbone's embedding dimension. Dimension is probed from the sidecar
    ``outputs`` schema — specifically the output with ``output_purpose:
    "embeddings"``. If unknown, the index is deferred until next startup.
    """
    try:
        from nomarr.components.ml.ml_discovery_comp import discover_heads

        heads = discover_heads(models_dir)
    except Exception:
        return

    # Group heads by backbone, take first to probe embed_dim
    seen: set[str] = set()
    for head in heads:
        if head.backbone in seen:
            continue
        seen.add(head.backbone)

        collection_name = f"vectors_track__{head.backbone}"
        if not db.has_collection(collection_name):
            continue

        # Probe embedding dimension from sidecar outputs with output_purpose="embeddings"
        embed_dim: int | None = None
        if head.embedding_sidecar:
            outputs = head.embedding_sidecar.outputs
            if outputs and isinstance(outputs, list):
                for output in outputs:
                    if (
                        isinstance(output, dict)
                        and output.get("output_purpose") == "embeddings"
                    ):
                        shape = output.get("shape")
                        if isinstance(shape, list) and len(shape) >= 2:
                            embed_dim = int(shape[-1])
                        break

        if embed_dim is None or embed_dim <= 0:
            logger.info(
                "[bootstrap] Cannot determine embed_dim for %s — vector index deferred",
                head.backbone,
            )
            continue

        # Check if vector index already exists
        coll = db.collection(collection_name)
        existing_indexes = coll.indexes()
        has_vector_index = any(
            idx.get("type") == "vector" for idx in existing_indexes  # type: ignore[union-attr]
        )
        if has_vector_index:
            continue

        try:
            coll.add_index(  # type: ignore[attr-defined]  # exists in python-arango 8.x, stubs incomplete
                {
                    "type": "vector",
                    "fields": ["vector"],
                    "params": {
                        "metric": "cosine",
                        "dimension": embed_dim,
                        "nLists": 10,
                    },
                },
            )
            logger.info(
                "[bootstrap] Created vector index on %s (dim=%d, metric=cosine)",
                collection_name,
                embed_dim,
            )
        except Exception:
            logger.warning(
                "[bootstrap] Failed to create vector index on %s (dim=%d) — will retry next startup",
                collection_name,
                embed_dim,
                exc_info=True,
            )
