from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from arango.exceptions import CollectionCreateError, DocumentInsertError, GraphCreateError, IndexCreateError

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
MIGRATION_VERSION: str = "0.2.1"
DESCRIPTION: str = "Schema refactor — edges, graphs, locks, file state graph, stale index cleanup"


def upgrade(db: DatabaseLike) -> None:
    """Create schema objects, migrate data, and clean up stale indexes idempotently.

    Phases:
     1. DDL — new collections, edge collections, indexes, graphs
     2. Seed file state vertices (original + completion set)
     3. Index verification on file_has_state
     4. Data migration — populate edges from FK fields
     5. Lock migration — consolidate old lock collections into locks
     6. Edge repointing — ml_tagged → tagged; reconciled → tags_written + tags_current
     7. Strip legacy payload attributes from file_has_state edges
     8. Seed negative state edges for files missing axis coverage
     9. Drop stale FK-based indexes BEFORE nullifying fields
    10. Nullify FK fields (after indexes dropped)
    11. Add tag_model_output indexes
    12. Verification — log edge counts and residual payload check

    Safe to run multiple times — all operations use guards.

    Args:
        db: ArangoDB database handle.
    """
    # =========================================================================
    # Phase 1 — DDL: New collections and edges
    # =========================================================================

    # locks collection (consolidated from ml_capacity_probe_locks, vector_promotion_locks)
    if not db.has_collection("locks"):
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("locks")
            logger.info("[V021] Created document collection 'locks'")

    # library_scans collection for separated scan state
    if not db.has_collection("library_scans"):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection("library_scans")  # type: ignore[union-attr]
            logger.info("[V021] Created document collection library_scans")

    # Edge collections with bidirectional indexes
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

        coll = db.collection(coll_name)  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_from", "_to"], unique=True)  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_from"])  # type: ignore[union-attr]

    # TTL index for auto-cleanup of expired locks
    with contextlib.suppress(IndexCreateError):
        db.collection("locks").add_ttl_index(fields=["expires_at"], expiry_time=0)  # type: ignore[union-attr]

    # Unique composite index on locks for duplicate prevention
    with contextlib.suppress(IndexCreateError):
        db.collection("locks").add_persistent_index(  # type: ignore[union-attr]
            fields=["lock_type", "target_key"], unique=True
        )

    # library_graph
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

    # file_graph
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

    # ml_graph
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

    # =========================================================================
    # Phase 2 — Seed file state vertices
    # =========================================================================

    # Combined set: original V021 states + V022 completion states
    all_file_states = [
        # Original V021
        "scanned",
        "too_short",
        "vectors_extracted",
        "tags_written",
        "errored",
        # V022 completion
        "tagged",
        "not_tagged",
        "not_too_short",
        "not_calibrated",
        "tags_not_written",
        "tags_current",
        "tags_stale",
        "not_scanned",
        "not_vectors_extracted",
        "not_errored",
    ]

    if db.has_collection("file_states"):
        file_states_coll = db.collection("file_states")  # type: ignore[union-attr]
        for state in all_file_states:
            with contextlib.suppress(DocumentInsertError):
                file_states_coll.insert({"_key": state}, silent=True)  # type: ignore[union-attr]
                logger.info(f"[V021] Inserted seed document file_states/{state}")

    # =========================================================================
    # Phase 3 — Index verification on file_has_state
    # =========================================================================

    if db.has_collection("file_has_state"):
        fhs_coll = db.collection("file_has_state")  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            fhs_coll.add_persistent_index(fields=["_to"])  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            fhs_coll.add_persistent_index(fields=["_from", "_to"], unique=True)  # type: ignore[union-attr]
        logger.info("[V021] Verified indexes on file_has_state")

    # =========================================================================
    # Phase 4 — Data migration: Populate edges from FK fields
    # =========================================================================

    # library_contains_file from library_files.library_id
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

    # library_contains_folder from library_folders.library_id
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

    # library_has_scan — migrate library scan state to library_scans collection
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

                UPSERT { _key: lib._key }
                INSERT scan_doc
                UPDATE scan_doc
                IN library_scans

                UPSERT { _from: lib._id, _to: CONCAT("library_scans/", lib._key) }
                INSERT { _from: lib._id, _to: CONCAT("library_scans/", lib._key) }
                UPDATE {}
                IN library_has_scan
            """
        )
        logger.info("[V021] Migrated library scan state to library_scans collection")

    # model_has_output from ml_model_outputs.model_id
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

    # model_has_calibration from calibration_state.model_key
    if db.has_collection("calibration_state") and db.has_collection("ml_models"):
        result = db.aql.execute(  # type: ignore[union-attr]
            """
            LET edge_count = (
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

                    FOR model IN ml_models
                        FILTER model.backbone == backbone
                           AND model.embedder_release_date == iso_date

                        INSERT { _from: model._id, _to: cs._id }
                        INTO model_has_calibration OPTIONS { ignoreErrors: true }
                        RETURN 1
            )
            RETURN LENGTH(edge_count)
            """
        )
        edges_created = next(result, 0)  # type: ignore[arg-type]
        logger.info(f"[V021] Created {edges_created} model_has_calibration edges")

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

    # file_has_segment_stats from segment_scores_stats.file_id
    if db.has_collection("segment_scores_stats"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN segment_scores_stats
                FILTER doc.file_id != null
                INSERT { _from: doc.file_id, _to: doc._id }
                INTO file_has_segment_stats OPTIONS { ignoreErrors: true }
            """
        )
        logger.info("[V021] Populated file_has_segment_stats edges from segment_scores_stats.file_id")

    # file_has_vectors from all vectors_track_* collections
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

    # =========================================================================
    # Phase 5 — Lock migration
    # =========================================================================

    # Migrate ml_capacity_probe_locks → locks with lock_type: "capacity_probe"
    if db.has_collection("ml_capacity_probe_locks"):
        db.aql.execute(  # type: ignore[union-attr]
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

    # Migrate vector_promotion_locks → locks with lock_type: "vector_promotion"
    if db.has_collection("vector_promotion_locks"):
        db.aql.execute(  # type: ignore[union-attr]
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

    # Drop old lock collections
    if db.has_collection("ml_capacity_probe_locks"):
        db.delete_collection("ml_capacity_probe_locks")
        logger.info("[V021] Dropped ml_capacity_probe_locks")

    if db.has_collection("vector_promotion_locks"):
        db.delete_collection("vector_promotion_locks")
        logger.info("[V021] Dropped vector_promotion_locks")

    # =========================================================================
    # Phase 6 — Edge repointing
    # =========================================================================

    # Repoint ml_tagged → tagged (THREE SEPARATE AQL CALLS)
    if db.has_collection("file_has_state"):
        # Step 1: READ edges to repoint
        repoint_read_cursor = db.aql.execute(  # type: ignore[union-attr]
            """
            FOR e IN file_has_state
                FILTER e._to == "file_states/ml_tagged"
                RETURN { _key: e._key, _from: e._from }
            """
        )
        edges = list(repoint_read_cursor)  # type: ignore[arg-type]
        repoint_count = len(edges)

        if edges:
            # Step 2: REMOVE old edges
            db.aql.execute(  # type: ignore[union-attr]
                """
                FOR doc IN @edges
                    REMOVE doc IN file_has_state
                """,
                bind_vars={"edges": edges},
            )
            from_ids = [e["_from"] for e in edges]
            # Step 3: INSERT new edges to tagged
            db.aql.execute(  # type: ignore[union-attr]
                """
                FOR f_id IN @from_ids
                    INSERT { _from: f_id, _to: "file_states/tagged" }
                    INTO file_has_state OPTIONS { ignoreErrors: true }
                """,
                bind_vars={"from_ids": from_ids},
            )
        logger.info(f"[V021] Repointed {repoint_count} ml_tagged → tagged edges")

        # Split reconciled → tags_written + tags_current (FOUR SEPARATE AQL CALLS)
        # Step 1: READ edges to split
        split_read_cursor = db.aql.execute(  # type: ignore[union-attr]
            """
            FOR e IN file_has_state
                FILTER e._to == "file_states/reconciled"
                RETURN { _key: e._key, _from: e._from }
            """
        )
        reconciled_edges = list(split_read_cursor)  # type: ignore[arg-type]
        split_count = len(reconciled_edges)

        if reconciled_edges:
            # Step 2: REMOVE old edges
            db.aql.execute(  # type: ignore[union-attr]
                """
                FOR doc IN @edges
                    REMOVE doc IN file_has_state
                """,
                bind_vars={"edges": reconciled_edges},
            )
            from_ids = [e["_from"] for e in reconciled_edges]
            # Step 3a: INSERT tags_written edges
            db.aql.execute(  # type: ignore[union-attr]
                """
                FOR f_id IN @from_ids
                    INSERT { _from: f_id, _to: "file_states/tags_written" }
                    INTO file_has_state OPTIONS { ignoreErrors: true }
                """,
                bind_vars={"from_ids": from_ids},
            )
            # Step 3b: INSERT tags_current edges
            db.aql.execute(  # type: ignore[union-attr]
                """
                FOR f_id IN @from_ids
                    INSERT { _from: f_id, _to: "file_states/tags_current" }
                    INTO file_has_state OPTIONS { ignoreErrors: true }
                """,
                bind_vars={"from_ids": from_ids},
            )
        logger.info(f"[V021] Split {split_count} reconciled → tags_written + tags_current edges")

    # =========================================================================
    # Phase 7 — Strip legacy payload from file_has_state
    # =========================================================================

    if db.has_collection("file_has_state"):
        strip_cursor = db.aql.execute(  # type: ignore[union-attr]
            """
            FOR e IN file_has_state
                FILTER e.version != null
                    OR e.hash != null
                    OR e.mode != null
                    OR e.tagged_at != null
                    OR e.calibrated_at != null
                    OR e.calibration_hash != null
                    OR e.written_at != null
                    OR e.has_namespace != null
                UPDATE e WITH {
                    version: null,
                    hash: null,
                    mode: null,
                    tagged_at: null,
                    calibrated_at: null,
                    calibration_hash: null,
                    written_at: null,
                    has_namespace: null
                } IN file_has_state OPTIONS { keepNull: false }
                RETURN 1
            """
        )
        strip_count = len(list(strip_cursor))  # type: ignore[arg-type]
        logger.info(f"[V021] Stripped payload attributes from {strip_count} edges")

    # =========================================================================
    # Phase 8 — Seed negative states
    # =========================================================================

    state_axes: list[tuple[str, str]] = [
        ("tagged", "not_tagged"),
        ("too_short", "not_too_short"),
        ("calibrated", "not_calibrated"),
        ("tags_written", "tags_not_written"),
        ("tags_current", "tags_stale"),
        ("scanned", "not_scanned"),
        ("vectors_extracted", "not_vectors_extracted"),
        ("errored", "not_errored"),
    ]

    if db.has_collection("library_files") and db.has_collection("file_has_state"):
        for positive, negative in state_axes:
            positive_id = f"file_states/{positive}"
            negative_id = f"file_states/{negative}"

            # Step 1: READ files missing axis coverage (separate from write)
            collect_cursor = db.aql.execute(  # type: ignore[union-attr]
                """
                FOR f IN library_files
                    LET has_axis = FIRST(
                        FOR e IN file_has_state
                            FILTER e._from == f._id
                               AND (e._to == @positive OR e._to == @negative)
                            LIMIT 1
                            RETURN true
                    )
                    FILTER has_axis == null
                    RETURN f._id
                """,
                bind_vars={"positive": positive_id, "negative": negative_id},
            )
            files_to_seed = list(collect_cursor)  # type: ignore[arg-type]
            seed_count = len(files_to_seed)

            # Step 2: WRITE negative state edges (separate AQL call)
            if files_to_seed:
                db.aql.execute(  # type: ignore[union-attr]
                    """
                    FOR f_id IN @file_ids
                        INSERT { _from: f_id, _to: @negative }
                        INTO file_has_state OPTIONS { ignoreErrors: true }
                    """,
                    bind_vars={"file_ids": files_to_seed, "negative": negative_id},
                )

            logger.info(f"[V021] Seeded {seed_count} negative edges for axis {positive}/{negative}")

    # =========================================================================
    # Phase 9 — DROP ALL stale indexes BEFORE nullifying fields
    # =========================================================================

    # library_files: drop all persistent indexes referencing library_id
    if db.has_collection("library_files"):
        coll = db.collection("library_files")  # type: ignore[union-attr]
        for idx in coll.indexes():  # type: ignore[union-attr]
            if idx.get("type") == "persistent" and "library_id" in (idx.get("fields") or []):
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info(f"[V021] Dropped index {idx['fields']} from library_files")

    # library_folders: drop all persistent indexes referencing library_id
    if db.has_collection("library_folders"):
        coll = db.collection("library_folders")  # type: ignore[union-attr]
        for idx in coll.indexes():  # type: ignore[union-attr]
            if idx.get("type") == "persistent" and "library_id" in (idx.get("fields") or []):
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info(f"[V021] Dropped index {idx['fields']} from library_folders")

    # ml_model_outputs: drop all persistent indexes referencing model_id
    if db.has_collection("ml_model_outputs"):
        coll = db.collection("ml_model_outputs")  # type: ignore[union-attr]
        for idx in coll.indexes():  # type: ignore[union-attr]
            if idx.get("type") == "persistent" and "model_id" in (idx.get("fields") or []):
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info(f"[V021] Dropped index {idx['fields']} from ml_model_outputs")

    # segment_scores_stats: drop all persistent indexes referencing file_id
    if db.has_collection("segment_scores_stats"):
        coll = db.collection("segment_scores_stats")  # type: ignore[union-attr]
        for idx in coll.indexes():  # type: ignore[union-attr]
            if idx.get("type") == "persistent" and "file_id" in (idx.get("fields") or []):
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info(f"[V021] Dropped index {idx['fields']} from segment_scores_stats")

    # meta: drop meta.key index — _key provides O(1) lookup
    if db.has_collection("meta"):
        coll = db.collection("meta")  # type: ignore[union-attr]
        for idx in coll.indexes():  # type: ignore[union-attr]
            if idx.get("type") == "persistent" and "key" in (idx.get("fields") or []):
                coll.delete_index(idx["id"])  # type: ignore[union-attr]
                logger.info("[V021] Dropped meta.key index")
                break

    # =========================================================================
    # Phase 10 — Nullify FK fields (after indexes dropped)
    # =========================================================================

    # library_files.library_id
    if db.has_collection("library_files"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR file IN library_files
                UPDATE file WITH { library_id: null } IN library_files
                OPTIONS { keepNull: false }
            """
        )
        logger.info("[V021] Dropped library_id field from library_files")

    # library_folders.library_id
    if db.has_collection("library_folders"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR folder IN library_folders
                UPDATE folder WITH { library_id: null } IN library_folders
                OPTIONS { keepNull: false }
            """
        )
        logger.info("[V021] Dropped library_id field from library_folders")

    # ml_model_outputs: nullify model_id, created_at, updated_at
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

    # calibration_state: nullify model_key, version, updated_at, last_computation_at
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

    # segment_scores_stats: nullify file_id
    if db.has_collection("segment_scores_stats"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN segment_scores_stats
                UPDATE doc WITH { file_id: null } IN segment_scores_stats
                OPTIONS { keepNull: false }
            """
        )
        logger.info("[V021] Dropped file_id field from segment_scores_stats")

    # vectors_track_*: nullify file_id
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

    # libraries: drop scan fields (migrated to library_scans)
    if db.has_collection("libraries"):
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

    # =========================================================================
    # Phase 11 — Add tag_model_output indexes
    # =========================================================================

    if db.has_collection("tag_model_output"):
        coll = db.collection("tag_model_output")  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_from"])  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            coll.add_persistent_index(fields=["_from", "_to"], unique=True)  # type: ignore[union-attr]
        logger.info("[V021] Added _from and _from+_to indexes to tag_model_output")

    # =========================================================================
    # Phase 12 — Verification
    # =========================================================================

    if db.has_collection("file_has_state"):
        total_cursor = db.aql.execute(  # type: ignore[union-attr]
            "RETURN LENGTH(file_has_state)"
        )
        total_edges = next(iter(total_cursor))  # type: ignore[arg-type]
        logger.info(f"[V021] Verification — total file_has_state edges: {total_edges}")

        dist_cursor = db.aql.execute(  # type: ignore[union-attr]
            """
            FOR e IN file_has_state
                COLLECT target = e._to WITH COUNT INTO cnt
                RETURN { target, cnt }
            """
        )
        dist_results = list(dist_cursor)  # type: ignore[arg-type]
        logger.info("[V021] Verification — edges per target state:")
        for row in dist_results:
            logger.info(f"[V021]   {row['target']}: {row['cnt']}")

        payload_cursor = db.aql.execute(  # type: ignore[union-attr]
            """
            FOR e IN file_has_state
                FILTER e.version != null
                    OR e.hash != null
                    OR e.mode != null
                    OR e.tagged_at != null
                    OR e.calibrated_at != null
                    OR e.calibration_hash != null
                    OR e.written_at != null
                    OR e.has_namespace != null
                COLLECT WITH COUNT INTO cnt
                RETURN cnt
            """
        )
        payload_count = next(iter(payload_cursor))  # type: ignore[arg-type]
        logger.info(f"[V021] Verification — edges with residual payload attributes: {payload_count}")
