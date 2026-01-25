"""ArangoDB schema bootstrap component.

Schema initialization (collections, indexes, graphs) - separated from persistence layer.
All operations are idempotent (safe to run multiple times).

ARCHITECTURAL NOTE:
This component lives in components/platform, NOT persistence/.
Rationale: Schema bootstrap may evolve to include non-DB setup (directories, default configs).
Persistence layer is "AQL only" - no upward dependencies.
"""

import logging

from arango.exceptions import CollectionCreateError, GraphCreateError, IndexCreateError

from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)


def ensure_schema(db: DatabaseLike) -> None:
    """Ensure all collections, indexes, and graphs exist.

    Idempotent - safe to call on every startup.
    Creates missing collections/indexes but does NOT alter existing ones.

    Args:
        db: ArangoDB database handle
    """
    _create_collections(db)
    _create_indexes(db)
    _create_graphs(db)
    _validate_no_legacy_calibration(db)


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
    ]

    for collection_name in document_collections:
        if not db.has_collection(collection_name):
            try:
                db.create_collection(collection_name)
            except CollectionCreateError:
                pass  # Collection already exists (race condition)

    # Edge collections
    edge_collections = [
        "song_tag_edges",  # song→tag relationships (unified)
    ]

    for edge_collection_name in edge_collections:
        if not db.has_collection(edge_collection_name):
            try:
                db.create_collection(edge_collection_name, edge=True)
            except CollectionCreateError:
                pass  # Collection already exists (race condition)


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
    _ensure_index(
        db,
        "library_files",
        "persistent",
        ["library_id", "path"],
        unique=True,
    )
    _ensure_index(
        db,
        "library_files",
        "persistent",
        ["chromaprint"],
        sparse=True,  # Only index non-null values
    )

    # library_folders indexes
    _ensure_index(db, "library_folders", "persistent", ["library_id"])
    _ensure_index(
        db,
        "library_folders",
        "persistent",
        ["library_id", "path"],
        unique=True,
    )

    # sessions TTL index (auto-expire based on expiry_timestamp)
    _ensure_index(
        db,
        "sessions",
        "ttl",
        ["expiry_timestamp"],
        expireAfter=0,  # Expire immediately when timestamp passes
    )

    # calibration_state indexes (NEW - histogram-based calibration)
    _ensure_index(
        db,
        "calibration_state",
        "persistent",
        ["calibration_def_hash"],
        unique=True,
        sparse=False,
    )
    _ensure_index(
        db,
        "calibration_state",
        "persistent",
        ["updated_at"],
        unique=False,
        sparse=False,
    )

    # calibration_history indexes (NEW - optional drift tracking)
    _ensure_index(
        db,
        "calibration_history",
        "persistent",
        ["calibration_key"],
        unique=False,
        sparse=False,
    )
    _ensure_index(
        db,
        "calibration_history",
        "persistent",
        ["snapshot_at"],
        unique=False,
        sparse=False,
    )

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


def _ensure_index(
    db: DatabaseLike,
    collection: str,
    index_type: str,
    fields: list[str],
    unique: bool = False,
    sparse: bool = False,
    expireAfter: int | None = None,
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

        # Build index spec
        spec = {
            "type": index_type,
            "fields": fields,
            "unique": unique,
            "sparse": sparse,
        }

        if index_type == "ttl" and expireAfter is not None:
            spec["expireAfter"] = expireAfter

        coll.add_persistent_index(fields=fields, unique=unique, sparse=sparse)
    except IndexCreateError:
        pass  # Index already exists


def _create_graphs(db: DatabaseLike) -> None:
    """Create named graphs for traversals.

    Creates "tag_graph" for song→tag relationships.
    """
    graph_name = "tag_graph"

    if not db.has_graph(graph_name):
        try:
            db.create_graph(
                name=graph_name,
                edge_definitions=[
                    {
                        "edge_collection": "song_tag_edges",
                        "from_vertex_collections": ["library_files"],
                        "to_vertex_collections": ["tags"],
                    }
                ],
            )
        except GraphCreateError:
            pass  # Graph already exists


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

    # TAG_UNIFICATION_REFACTOR: Legacy tag collections
    legacy_tag_collections = [
        "library_tags",
        "file_tags",
        "artists",
        "albums",
        "genres",
        "labels",
        "years",
    ]
    found_legacy_tags = [name for name in legacy_tag_collections if db.has_collection(name)]

    if found_legacy_tags:
        logger.error(
            "Legacy tag collections detected: %s. "
            "These have been replaced by the unified 'tags' + 'song_tag_edges' schema. "
            "Drop them manually and rescan libraries.",
            ", ".join(found_legacy_tags),
        )
