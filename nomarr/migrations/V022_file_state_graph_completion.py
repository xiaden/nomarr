from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
MIGRATION_VERSION: str = "0.2.2"
DESCRIPTION: str = "File state graph completion — new vertices, index verification, edge repointing, payload stripping, negative state seeding"


def upgrade(db: DatabaseLike) -> None:
    """Complete the file state graph model.

    This migration:
    - Seeds new file_states vertices for negative states and renamed states
    - Verifies indexes on file_has_state edges
    - Repoints ml_tagged edges to tagged
    - Splits reconciled edges into tags_written + tags_current
    - Strips legacy payload attributes from all edges
    - Seeds negative state edges for files missing axis coverage
    - Logs verification summary

    Safe to run multiple times — all operations use guards.

    Args:
        db: ArangoDB database handle.
    """
    from arango.exceptions import DocumentInsertError, IndexCreateError

    # === Phase 1: Vertex seeding ===

    new_file_states = [
        "tagged",
        "not_tagged",
        "not_too_short",
        "not_calibrated",
        "tags_written",
        "tags_not_written",
        "tags_current",
        "tags_stale",
        "not_scanned",
        "not_vectors_extracted",
        "not_errored",
    ]

    file_states_coll = db.collection("file_states")  # type: ignore[union-attr]
    for state in new_file_states:
        if not file_states_coll.get(state):  # type: ignore[union-attr]
            with contextlib.suppress(DocumentInsertError):
                file_states_coll.insert({"_key": state}, silent=True)  # type: ignore[union-attr]
                logger.info(f"[V022] Inserted seed document file_states/{state}")

    # === Phase 1: Index verification ===

    fhs_coll = db.collection("file_has_state")  # type: ignore[union-attr]
    with contextlib.suppress(IndexCreateError):
        fhs_coll.add_persistent_index(fields=["_to"])  # type: ignore[union-attr]
    with contextlib.suppress(IndexCreateError):
        fhs_coll.add_persistent_index(fields=["_from", "_to"], unique=True)  # type: ignore[union-attr]
    logger.info("[V022] Verified indexes on file_has_state")

    # === Phase 2: Edge repointing ===

    # Repoint ml_tagged → tagged
    # Step 1: Collect edges to repoint (READ only)
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
        # Step 2: Remove old edges (WRITE only, bind vars)
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN @edges
                REMOVE doc IN file_has_state
            """,
            bind_vars={"edges": edges},
        )
        from_ids = [e["_from"] for e in edges]
        # Step 3: Insert new edges to tagged (WRITE only, bind vars)
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR f_id IN @from_ids
                INSERT { _from: f_id, _to: "file_states/tagged" }
                INTO file_has_state OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"from_ids": from_ids},
        )
    logger.info(f"[V022] Repointed {repoint_count} ml_tagged → tagged edges")

    # Split reconciled → tags_written + tags_current
    # Step 1: Collect edges to split (READ from file_has_state)
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
        # Step 2: Remove old edges (WRITE to file_has_state)
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN @edges
                REMOVE doc IN file_has_state
            """,
            bind_vars={"edges": reconciled_edges},
        )
        from_ids = [e["_from"] for e in reconciled_edges]
        # Step 3a: Insert tags_written edges (WRITE to file_has_state)
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR f_id IN @from_ids
                INSERT { _from: f_id, _to: "file_states/tags_written" }
                INTO file_has_state OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"from_ids": from_ids},
        )
        # Step 3b: Insert tags_current edges (WRITE to file_has_state)
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR f_id IN @from_ids
                INSERT { _from: f_id, _to: "file_states/tags_current" }
                INTO file_has_state OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"from_ids": from_ids},
        )

    logger.info(f"[V022] Split {split_count} reconciled → tags_written + tags_current edges")

    # === Phase 3: Strip legacy payload attributes ===

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
    strip_results = list(strip_cursor)  # type: ignore[arg-type]
    strip_count = len(strip_results)
    logger.info(f"[V022] Stripped payload attributes from {strip_count} edges")

    # === Phase 4: Seed negative states ===

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

    for positive, negative in state_axes:
        positive_id = f"file_states/{positive}"
        negative_id = f"file_states/{negative}"
        # Step 1: Find files missing this axis (READ from library_files + file_has_state)
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

        # Step 2: Batch insert negative state edges (WRITE to file_has_state)
        if files_to_seed:
            db.aql.execute(  # type: ignore[union-attr]
                """
                FOR f_id IN @file_ids
                    INSERT { _from: f_id, _to: @negative }
                    INTO file_has_state OPTIONS { ignoreErrors: true }
                """,
                bind_vars={"file_ids": files_to_seed, "negative": negative_id},
            )

        logger.info(f"[V022] Seeded {seed_count} negative edges for axis {positive}/{negative}")

    # === Phase 5: Verification ===

    total_cursor = db.aql.execute(  # type: ignore[union-attr]
        "RETURN LENGTH(file_has_state)"
    )
    total_edges = next(iter(total_cursor))  # type: ignore[arg-type]
    logger.info(f"[V022] Verification — total file_has_state edges: {total_edges}")

    dist_cursor = db.aql.execute(  # type: ignore[union-attr]
        """
        FOR e IN file_has_state
            COLLECT target = e._to WITH COUNT INTO cnt
            RETURN { target, cnt }
        """
    )
    dist_results = list(dist_cursor)  # type: ignore[arg-type]
    logger.info("[V022] Verification — edges per target state:")
    for row in dist_results:
        logger.info(f"[V022]   {row['target']}: {row['cnt']}")

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
    logger.info(f"[V022] Verification — edges with residual payload attributes: {payload_count}")
