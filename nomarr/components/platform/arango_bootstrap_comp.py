"""ArangoDB schema bootstrap component.

Schema initialization (collections, indexes, graphs) - separated from persistence layer.
All operations are idempotent (safe to run multiple times).

ARCHITECTURAL NOTE:
This component lives in components/platform, NOT persistence/.
Rationale: Schema bootstrap may evolve to include non-DB setup (directories, default configs).
Persistence layer is "AQL only" - no upward dependencies.
"""

import logging

from arango.database import StandardDatabase
from arango.exceptions import CollectionCreateError, GraphCreateError, IndexCreateError

logger = logging.getLogger(__name__)


def ensure_schema(db: StandardDatabase) -> None:
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


def _create_collections(db: StandardDatabase) -> None:
    """Create document and edge collections."""
    # Document collections
    document_collections = [
        "meta",
        "libraries",
        "library_files",
        "library_folders",
        "library_tags",
        "sessions",
        "calibration_state",
        "calibration_history",
        "health",
        "worker_claims",  # Discovery worker claims (Phase 2)
        # Metadata entity vertex collections
        "artists",
        "albums",
        "labels",
        "genres",
        "years",
    ]

    for collection_name in document_collections:
        if not db.has_collection(collection_name):
            try:
                db.create_collection(collection_name)
            except CollectionCreateError:
                pass  # Collection already exists (race condition)

    # Edge collections
    edge_collections = [
        "file_tags",  # file→tag relationships (ML tags)
        "song_tag_edges",  # entity→song relationships (metadata entities)
    ]

    for edge_collection_name in edge_collections:
        if not db.has_collection(edge_collection_name):
            try:
                db.create_collection(edge_collection_name, edge=True)
            except CollectionCreateError:
                pass  # Collection already exists (race condition)


def _create_indexes(db: StandardDatabase) -> None:
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

    # library_tags indexes
    _ensure_index(
        db,
        "library_tags",
        "persistent",
        ["key", "value", "is_nomarr_tag"],
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

    # file_tags composite index for histogram queries (histogram-based calibration)
    _ensure_index(
        db,
        "file_tags",
        "persistent",
        ["model_key", "head_name", "nomarr_only"],
        unique=False,
        sparse=False,
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

    # Entity collection indexes (for UI search/listing)
    for entity_collection in ["artists", "albums", "labels", "genres", "years"]:
        _ensure_index(
            db,
            entity_collection,
            "persistent",
            ["display_name"],
            unique=False,
            sparse=False,
        )

    # song_tag_edges indexes (entity→song metadata relationships)
    _ensure_index(
        db,
        "song_tag_edges",
        "persistent",
        ["rel", "_from"],  # Entity→songs navigation
        unique=False,
        sparse=False,
    )
    _ensure_index(
        db,
        "song_tag_edges",
        "persistent",
        ["rel", "_to"],  # Song→entities updates/cache rebuild
        unique=False,
        sparse=False,
    )


def _ensure_index(
    db: StandardDatabase,
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


def _create_graphs(db: StandardDatabase) -> None:
    """Create named graphs for traversals.

    Creates "file_tag_graph" for file→tag relationships.
    """
    graph_name = "file_tag_graph"

    if not db.has_graph(graph_name):
        try:
            db.create_graph(
                name=graph_name,
                edge_definitions=[
                    {
                        "edge_collection": "file_tags",
                        "from_vertex_collections": ["library_files"],
                        "to_vertex_collections": ["library_tags"],
                    }
                ],
            )
        except GraphCreateError:
            pass  # Graph already exists


def _validate_no_legacy_calibration(db: StandardDatabase) -> None:
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
