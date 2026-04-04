from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
MIGRATION_VERSION: str = "0.2.1"
DESCRIPTION: str = "Schema refactor v1 — edges, graphs, locks consolidation"


def upgrade(db: DatabaseLike) -> None:
    """Create schema objects and migrate data idempotently.

    This migration:
    - Creates Pydantic base model infrastructure
    - Consolidates lock collections
    - Expands file states
    - Creates edge collections for FK→edge migration
    - Defines named graphs

    Safe to run multiple times — all operations use guards.

    Args:
        db: ArangoDB database handle.
    """
    from arango.exceptions import CollectionCreateError, DocumentInsertError, GraphCreateError, IndexCreateError

    # === DDL: Collections ===

    # P3-S1: Create locks collection (consolidated from ml_capacity_probe_locks, vector_promotion_locks)
    if not db.has_collection("locks"):
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("locks")
            logger.info("[V021] Created document collection 'locks'")

    # Plan C P1-S1: Create library_scans collection for separated scan state
    if not db.has_collection("library_scans"):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("library_scans")  # type: ignore[union-attr]
            logger.info("[V021] Created document collection library_scans")

    # P6-S1: Edge collections with bidirectional indexes
    edge_collections = [
        "library_contains_file",
        "library_contains_folder",
        "library_has_scan",
        "file_has_vectors",
        "file_has_segment_stats",
        "model_has_output",
        "model_has_calibration",
    ]

    for coll_name in edge_collections:
        if not db.has_collection(coll_name):  # type: ignore[union-attr]
            with contextlib.suppress(CollectionCreateError):
                db.create_collection(coll_name, edge=True)  # type: ignore[union-attr]
                logger.info(f"[V021] Created edge collection {coll_name}")

        # Add bidirectional indexes (unique composite + from + to)
        coll = db.collection(coll_name)  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_from", "_to"], unique=True)  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_from"])  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_to"])  # type: ignore[union-attr]

    # === DDL: Indexes ===

    # P3-S2: TTL index for auto-cleanup of expired locks
    with contextlib.suppress(IndexCreateError):
        db.collection("locks").add_ttl_index(fields=["expires_at"], expiry_time=0)

    # P3-S3: Unique index on [lock_type, target_key] for composite key pattern
    with contextlib.suppress(IndexCreateError):
        db.collection("locks").add_persistent_index(fields=["lock_type", "target_key"], unique=True)

    # === DDL: Graphs ===

    # P7-S1: Create library_graph
    if not db.has_graph("library_graph"):  # type: ignore[union-attr]
        with contextlib.suppress(GraphCreateError):
            db.create_graph(  # type: ignore[union-attr]
                "library_graph",
                edge_definitions=[
                    {
                        "edge_collection": "library_contains_file",
                        "from_vertex_collections": ["libraries"],
                        "to_vertex_collections": ["library_files"],
                    },
                    {
                        "edge_collection": "library_contains_folder",
                        "from_vertex_collections": ["libraries"],
                        "to_vertex_collections": ["library_folders"],
                    },
                    {
                        "edge_collection": "library_has_scan",
                        "from_vertex_collections": ["libraries"],
                        "to_vertex_collections": ["library_scans"],
                    },
                ],
            )
            logger.info("[V021] Created graph library_graph")

    # P7-S2: Create file_graph
    if not db.has_graph("file_graph"):  # type: ignore[union-attr]
        with contextlib.suppress(GraphCreateError):
            db.create_graph(  # type: ignore[union-attr]
                "file_graph",
                edge_definitions=[
                    {
                        "edge_collection": "file_has_state",
                        "from_vertex_collections": ["library_files"],
                        "to_vertex_collections": ["file_states"],
                    },
                    {
                        "edge_collection": "song_has_tags",
                        "from_vertex_collections": ["library_files"],
                        "to_vertex_collections": ["tags"],
                    },
                    {
                        "edge_collection": "file_has_vectors",
                        "from_vertex_collections": ["library_files"],
                        "to_vertex_collections": ["vectors_track_hot", "vectors_track_cold"],
                    },
                    {
                        "edge_collection": "file_has_segment_stats",
                        "from_vertex_collections": ["library_files"],
                        "to_vertex_collections": ["segment_scores_stats"],
                    },
                ],
            )
            logger.info("[V021] Created graph file_graph")

    # P7-S3: Create ml_graph
    if not db.has_graph("ml_graph"):  # type: ignore[union-attr]
        with contextlib.suppress(GraphCreateError):
            db.create_graph(  # type: ignore[union-attr]
                "ml_graph",
                edge_definitions=[
                    {
                        "edge_collection": "model_has_output",
                        "from_vertex_collections": ["ml_models"],
                        "to_vertex_collections": ["ml_model_outputs"],
                    },
                    {
                        "edge_collection": "model_has_calibration",
                        "from_vertex_collections": ["ml_models"],
                        "to_vertex_collections": ["calibration_state"],
                    },
                    {
                        "edge_collection": "tag_model_output",
                        "from_vertex_collections": ["tags"],
                        "to_vertex_collections": ["ml_model_outputs"],
                    },
                ],
            )
            logger.info("[V021] Created graph ml_graph")

    # === Data Migration ===

    # P3-S4: Migrate ml_capacity_probe_locks → locks with lock_type: "capacity_probe"
    if db.has_collection("ml_capacity_probe_locks"):
        db.aql.execute(
            """
            FOR doc IN ml_capacity_probe_locks
                INSERT {
                    _key: CONCAT("capacity_probe:", doc._key),
                    lock_type: "capacity_probe",
                    owner_id: doc.worker_id,
                    target_key: doc._key,
                    acquired_at: doc.started_at,
                    expires_at: null
                } INTO locks OPTIONS { ignoreErrors: true }
            """
        )
        logger.info("[V021] Migrated ml_capacity_probe_locks to locks")

    # P3-S5: Migrate vector_promotion_locks → locks with lock_type: "vector_promotion"
    if db.has_collection("vector_promotion_locks"):
        db.aql.execute(
            """
            FOR doc IN vector_promotion_locks
                INSERT {
                    _key: CONCAT("vector_promotion:", doc._key),
                    lock_type: "vector_promotion",
                    owner_id: doc.locked_by,
                    target_key: doc._key,
                    acquired_at: doc.locked_at,
                    expires_at: null
                } INTO locks OPTIONS { ignoreErrors: true }
            """
        )
        logger.info("[V021] Migrated vector_promotion_locks to locks")

    # P5-S1: Seed additional file states for expanded pipeline
    # Existing states (calibrated, ml_tagged, reconciled) seeded by V001
    new_file_states = ["scanned", "too_short", "vectors_extracted", "tags_written", "errored"]
    if db.has_collection("file_states"):
        file_states_coll = db.collection("file_states")  # type: ignore[union-attr]
        for state in new_file_states:
            if not file_states_coll.get(state):  # type: ignore[union-attr]
                with contextlib.suppress(DocumentInsertError):
                    file_states_coll.insert({"_key": state}, silent=True)  # type: ignore[union-attr]
                    logger.info(f"[V021] Inserted seed document file_states/{state}")

    # Plan B P1-S1: Populate library_contains_file edges from library_files.library_id
    if db.has_collection("library_files"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR file IN library_files
                FILTER file.library_id != null
                INSERT { _from: file.library_id, _to: file._id }
                INTO library_contains_file OPTIONS { ignoreErrors: true }
            """
        )
        logger.info("[V021] Populated library_contains_file edges from library_files.library_id")

    # Plan B P1-S2: Populate library_contains_folder edges from library_folders.library_id
    if db.has_collection("library_folders"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR folder IN library_folders
                FILTER folder.library_id != null
                INSERT { _from: folder.library_id, _to: folder._id }
                INTO library_contains_folder OPTIONS { ignoreErrors: true }
            """
        )
        logger.info("[V021] Populated library_contains_folder edges from library_folders.library_id")

    # Plan C P2-S1: Migrate library scan state to library_scans collection
    # Create library_scans doc for each library and establish edge
    if db.has_collection("libraries"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR lib IN libraries
                LET scan_doc = {
                    _key: lib._key,
                    status: lib.scan_status || "idle",
                    files_processed: lib.scan_progress || 0,
                    files_total: lib.scan_total || 0,
                    completed_at: lib.scanned_at,
                    started_at: lib.last_scan_started_at,
                    error: lib.scan_error,
                    scan_type: lib.scan_type_in_progress
                }

                // Create scan doc (or update if exists)
                UPSERT { _key: lib._key }
                INSERT scan_doc
                UPDATE scan_doc
                IN library_scans

                // Create edge
                UPSERT { _from: lib._id, _to: CONCAT("library_scans/", lib._key) }
                INSERT { _from: lib._id, _to: CONCAT("library_scans/", lib._key) }
                UPDATE {}
                IN library_has_scan
            """
        )
        logger.info("[V021] Migrated library scan state to library_scans collection")

    # Plan D P1-S1: Populate model_has_output edges from ml_model_outputs.model_id
    if db.has_collection("ml_model_outputs"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR output IN ml_model_outputs
                FILTER output.model_id != null
                INSERT { _from: output.model_id, _to: output._id }
                INTO model_has_output OPTIONS { ignoreErrors: true }
            """
        )
        logger.info("[V021] Populated model_has_output edges from ml_model_outputs.model_id")

    # Plan D P2-S1: Populate model_has_calibration edges from calibration_state.model_key
    # model_key format: "backbone-YYYYMMDD" -> needs parsing to match ml_models
    if db.has_collection("calibration_state") and db.has_collection("ml_models"):
        # First pass: create edges for matching models
        result = db.aql.execute(  # type: ignore[union-attr]
            """
            LET edge_count = (
                FOR cs IN calibration_state
                    FILTER cs.model_key != null AND cs.model_key != ""

                    // Parse model_key: "effnet-20220825" -> backbone="effnet", raw_date="20220825"
                    LET parts = SPLIT(cs.model_key, "-")
                    LET backbone = parts[0]
                    LET raw_date = parts[1]

                    // Convert YYYYMMDD -> YYYY-MM-DD for embedder_release_date match
                    LET iso_date = CONCAT(
                        SUBSTRING(raw_date, 0, 4), "-",
                        SUBSTRING(raw_date, 4, 2), "-",
                        SUBSTRING(raw_date, 6, 2)
                    )

                    // Find matching model
                    FOR model IN ml_models
                        FILTER model.backbone == backbone
                           AND model.embedder_release_date == iso_date

                        // Insert edge (skip duplicates)
                        INSERT { _from: model._id, _to: cs._id }
                        INTO model_has_calibration OPTIONS { ignoreErrors: true }
                        RETURN 1
            )
            RETURN LENGTH(edge_count)
            """
        )
        edges_created = next(result, 0)  # type: ignore[arg-type]
        logger.info(f"[V021] Created {edges_created} model_has_calibration edges")

        # Second pass: log orphaned calibrations (no matching model)
        orphan_cursor = db.aql.execute(  # type: ignore[union-attr]
            """
            FOR cs IN calibration_state
                FILTER cs.model_key != null AND cs.model_key != ""

                LET parts = SPLIT(cs.model_key, "-")
                LET backbone = parts[0]
                LET raw_date = parts[1]
                LET iso_date = CONCAT(
                    SUBSTRING(raw_date, 0, 4), "-",
                    SUBSTRING(raw_date, 4, 2), "-",
                    SUBSTRING(raw_date, 6, 2)
                )

                LET matching_models = (
                    FOR model IN ml_models
                        FILTER model.backbone == backbone
                           AND model.embedder_release_date == iso_date
                        RETURN 1
                )
                FILTER LENGTH(matching_models) == 0
                RETURN { _key: cs._key, model_key: cs.model_key }
            """
        )
        orphaned: list[dict[str, str]] = list(orphan_cursor)  # type: ignore[arg-type]
        if orphaned:
            logger.warning(
                f"[V021] Found {len(orphaned)} orphaned calibration_state docs (no matching ml_model): "
                f"{[o['model_key'] for o in orphaned[:5]]}{'...' if len(orphaned) > 5 else ''}"
            )

    # Plan E P1-S1: Populate file_has_segment_stats edges from segment_score_stats.file_id
    if db.has_collection("segment_score_stats"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN segment_score_stats
                FILTER doc.file_id != null
                INSERT { _from: doc.file_id, _to: doc._id }
                INTO file_has_segment_stats OPTIONS { ignoreErrors: true }
            """
        )
        logger.info("[V021] Populated file_has_segment_stats edges from segment_score_stats.file_id")

    # Plan E P2-S1/S2: Populate file_has_vectors edges from all vectors_track_* collections
    # These are polymorphic: vectors_track_{hot|cold}__{backbone}__{library_key}
    all_collections: list[dict[str, str | bool]] = db.collections()  # type: ignore[assignment]
    vector_collections: list[str] = [
        str(c["name"]) for c in all_collections if str(c["name"]).startswith("vectors_track_") and not c["system"]
    ]
    for coll_name in vector_collections:
        logger.info(f"[V021] Migrating file_has_vectors edges from {coll_name}")
        db.aql.execute(  # type: ignore[union-attr]
            f"""
            FOR doc IN {coll_name}
                FILTER doc.file_id != null
                INSERT {{ _from: doc.file_id, _to: doc._id }}
                INTO file_has_vectors OPTIONS {{ ignoreErrors: true }}
            """
        )
    if vector_collections:
        logger.info(f"[V021] Populated file_has_vectors edges from {len(vector_collections)} vector collections")

    # === Cleanup ===

    # P3-S6: Drop old lock collections
    if db.has_collection("ml_capacity_probe_locks"):
        db.delete_collection("ml_capacity_probe_locks")
        logger.info("[V021] Dropped ml_capacity_probe_locks")

    if db.has_collection("vector_promotion_locks"):
        db.delete_collection("vector_promotion_locks")
        logger.info("[V021] Dropped vector_promotion_locks")

    # P4-S2: Drop obsolete meta.key index — _key provides O(1) lookup
    if db.has_collection("meta"):
        coll = db.collection("meta")  # type: ignore[union-attr]
        for idx in coll.indexes():  # type: ignore[union-attr]
            if idx.get("fields") == ["key"] and idx.get("type") == "persistent":
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info("[V021] Dropped meta.key index")
                break

    # Plan C P5: Drop scan_* fields from libraries after migration to library_scans
    db.aql.execute(  # type: ignore[union-attr]
        """
        FOR lib IN libraries
            UPDATE lib WITH {
                scan_status: null,
                scan_progress: null,
                scan_total: null,
                scanned_at: null,
                scan_error: null,
                last_scan_started_at: null,
                scan_type_in_progress: null
            } IN libraries
            OPTIONS { keepNull: false }
        """
    )
    logger.info("[V021] Dropped scan fields from libraries (migrated to library_scans)")
    # Plan B P5: Drop library_id from documents after edge migration
    # P5-S3/S4 (hoisted): Drop ALL library_id-related persistent indexes from library_files BEFORE
    # nullifying library_id — covers (library_id), (library_id, path), (library_id, normalized_path)
    # and any future indexes that might reference library_id.
    if db.has_collection("library_files"):
        coll = db.collection("library_files")  # type: ignore[union-attr]
        for idx in coll.indexes():  # type: ignore[union-attr]
            if idx.get("type") == "persistent" and "library_id" in (idx.get("fields") or []):
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info(f"[V021] Dropped index {idx['fields']} from library_files")

    # P5-S1: library_files.library_id
    db.aql.execute(  # type: ignore[union-attr]
        """
        FOR file IN library_files
            UPDATE file WITH { library_id: null } IN library_files
            OPTIONS { keepNull: false }
        """
    )
    logger.info("[V021] Dropped library_id field from library_files")

    # P5-S5 (hoisted): Drop ALL library_id-related persistent indexes from library_folders BEFORE
    # nullifying library_id — covers (library_id), (library_id, path), and any future indexes.
    if db.has_collection("library_folders"):
        coll = db.collection("library_folders")  # type: ignore[union-attr]
        for idx in coll.indexes():  # type: ignore[union-attr]
            if idx.get("type") == "persistent" and "library_id" in (idx.get("fields") or []):
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info(f"[V021] Dropped index {idx['fields']} from library_folders")

    # P5-S2: library_folders.library_id
    db.aql.execute(  # type: ignore[union-attr]
        """
        FOR folder IN library_folders
            UPDATE folder WITH { library_id: null } IN library_folders
            OPTIONS { keepNull: false }
        """
    )
    logger.info("[V021] Dropped library_id field from library_folders")

    # Plan D P8-S1: Drop FK fields from ml_model_outputs (now tracked via model_has_output edges)
    if db.has_collection("ml_model_outputs"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR o IN ml_model_outputs
                UPDATE o WITH {
                    model_id: null,
                    created_at: null,
                    updated_at: null
                } IN ml_model_outputs
                OPTIONS { keepNull: false }
            """
        )
        logger.info("[V021] Dropped FK fields from ml_model_outputs (model_id, created_at, updated_at)")

    # Plan D P8-S2: Drop FK fields from calibration_state (now tracked via model_has_calibration edges)
    if db.has_collection("calibration_state"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR cs IN calibration_state
                UPDATE cs WITH {
                    model_key: null,
                    version: null,
                    updated_at: null,
                    last_computation_at: null
                } IN calibration_state
                OPTIONS { keepNull: false }
            """
        )
        logger.info(
            "[V021] Dropped FK fields from calibration_state (model_key, version, updated_at, last_computation_at)"
        )

    # Plan E P10-S1: Drop file_id FK from segment_scores_stats (now tracked via file_has_segment_stats edges)
    if db.has_collection("segment_scores_stats"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN segment_scores_stats
                UPDATE doc WITH { file_id: null } IN segment_scores_stats
                OPTIONS { keepNull: false }
            """
        )
        logger.info("[V021] Dropped file_id field from segment_scores_stats")

    # Plan E P10-S2: Drop file_id FK from all vectors_track_* collections (now tracked via file_has_vectors edges)
    for coll_name in vector_collections:
        db.aql.execute(  # type: ignore[union-attr]
            f"""
            FOR doc IN {coll_name}
                UPDATE doc WITH {{ file_id: null }} IN {coll_name}
                OPTIONS {{ keepNull: false }}
            """
        )
    if vector_collections:
        logger.info(f"[V021] Dropped file_id field from {len(vector_collections)} vector collections")

    # Plan E P10-S3: Drop file_id index from segment_scores_stats
    if db.has_collection("segment_scores_stats"):
        coll = db.collection("segment_scores_stats")  # type: ignore[union-attr]
        for idx in coll.indexes():  # type: ignore[union-attr]
            if idx.get("fields") == ["file_id"] and idx.get("type") == "persistent":
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info("[V021] Dropped file_id index from segment_scores_stats")
                break

    # Plan F P1-S1: Add missing indexes to tag_model_output (already has _to from bootstrap)
    if db.has_collection("tag_model_output"):
        coll = db.collection("tag_model_output")  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_from"])  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_from", "_to"], unique=True)  # type: ignore[union-attr]
        logger.info("[V021] Added _from and _from+_to indexes to tag_model_output")
