"""ArangoDB schema bootstrap component.

Schema initialization (collections, indexes, graphs) - separated from persistence layer.
All operations are idempotent (safe to run multiple times).

ARCHITECTURAL NOTE:
This component lives in components/platform, NOT persistence/.
Rationale: Schema bootstrap may evolve to include non-DB setup (directories, default configs).
Persistence layer is "AQL only" - no upward dependencies.
"""

from arango.database import StandardDatabase
from arango.exceptions import CollectionCreateError, GraphCreateError, IndexCreateError


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


def _create_collections(db: StandardDatabase) -> None:
    """Create document and edge collections."""
    # Document collections
    document_collections = [
        "tag_queue",
        "meta",
        "libraries",
        "library_files",
        "calibration_queue",
        "library_tags",
        "sessions",
        "calibration_runs",
        "health",
    ]

    for collection_name in document_collections:
        if not db.has_collection(collection_name):
            try:
                db.create_collection(collection_name)
            except CollectionCreateError:
                pass  # Collection already exists (race condition)

    # Edge collection for file→tag relationships
    if not db.has_collection("file_tags"):
        try:
            db.create_collection("file_tags", edge=True)
        except CollectionCreateError:
            pass


def _create_indexes(db: StandardDatabase) -> None:
    """Create indexes for performance.

    Idempotent - skips existing indexes.
    """
    # tag_queue indexes
    _ensure_index(db, "tag_queue", "persistent", ["status"])
    _ensure_index(db, "tag_queue", "persistent", ["created_at"])

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

    # calibration_queue indexes
    _ensure_index(db, "calibration_queue", "persistent", ["status"])
    _ensure_index(db, "calibration_queue", "persistent", ["created_at"])

    # calibration_runs indexes
    _ensure_index(db, "calibration_runs", "persistent", ["run_id"], unique=True)
    _ensure_index(db, "calibration_runs", "persistent", ["created_at"])


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
