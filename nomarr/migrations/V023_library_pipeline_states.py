"""V023: create library pipeline state graph and seed initial library states."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.constants.file_states import (
    STATE_CALIBRATED,
    STATE_NOT_TAGGED,
    STATE_TAGGED,
    STATE_TAGS_WRITTEN,
)
from nomarr.helpers.constants.pipeline_states import (
    PIPELINE_APPLYING,
    PIPELINE_AWAITING_CALIBRATION,
    PIPELINE_CALIBRATING,
    PIPELINE_DONE,
    PIPELINE_IDLE,
    PIPELINE_ML_RUNNING,
    PIPELINE_SCANNING,
    PIPELINE_TOO_SMALL,
    PIPELINE_WRITE_READY,
    PIPELINE_WRITING,
)

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.3"
DESCRIPTION: str = "Create library pipeline state graph, seed singleton states, and derive initial library state edges"

_PIPELINE_STATE_IDS: tuple[str, ...] = (
    PIPELINE_IDLE,
    PIPELINE_SCANNING,
    PIPELINE_ML_RUNNING,
    PIPELINE_TOO_SMALL,
    PIPELINE_AWAITING_CALIBRATION,
    PIPELINE_CALIBRATING,
    PIPELINE_APPLYING,
    PIPELINE_WRITE_READY,
    PIPELINE_WRITING,
    PIPELINE_DONE,
)
_PIPELINE_GRAPH = "pipeline_graph"
_PIPELINE_VERTEX_COLLECTION = "library_pipeline_states"
_PIPELINE_EDGE_COLLECTION = "library_has_pipeline_state"


def _derive_pipeline_state(
    total_files: int,
    tagged_count: int,
    untagged_count: int,
    calibrated_count: int,
    written_count: int,
) -> str:
    """Derive the initial library pipeline state from file-state counts."""
    from nomarr.services.infrastructure.config_svc import INTERNAL_CALIBRATION_MIN_FILES

    if total_files == 0 or tagged_count == 0:
        return PIPELINE_IDLE
    if untagged_count > 0 or tagged_count < total_files:
        return PIPELINE_ML_RUNNING
    if tagged_count < INTERNAL_CALIBRATION_MIN_FILES:
        return PIPELINE_TOO_SMALL
    if calibrated_count < total_files:
        return PIPELINE_AWAITING_CALIBRATION
    if written_count < total_files:
        return PIPELINE_WRITE_READY
    return PIPELINE_DONE


def upgrade(db: DatabaseLike) -> None:
    """Create the pipeline state graph and seed derived state edges for existing libraries."""
    from arango.exceptions import (
        CollectionCreateError,
        DocumentInsertError,
        EdgeDefinitionCreateError,
        EdgeDefinitionReplaceError,
        GraphCreateError,
        IndexCreateError,
    )

    if not db.has_collection(_PIPELINE_VERTEX_COLLECTION):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection(_PIPELINE_VERTEX_COLLECTION)  # type: ignore[union-attr]
            logger.info("[V023] Created vertex collection %s", _PIPELINE_VERTEX_COLLECTION)

    if db.has_collection(_PIPELINE_VERTEX_COLLECTION):
        state_collection = db.collection(_PIPELINE_VERTEX_COLLECTION)  # type: ignore[union-attr]
        for state_id in _PIPELINE_STATE_IDS:
            state_key = state_id.rsplit("/", 1)[1]
            with contextlib.suppress(DocumentInsertError):
                state_collection.insert({"_key": state_key}, silent=True)  # type: ignore[union-attr]
                logger.info("[V023] Ensured seed vertex %s/%s", _PIPELINE_VERTEX_COLLECTION, state_key)

    if not db.has_collection(_PIPELINE_EDGE_COLLECTION):  # type: ignore[union-attr]
        with contextlib.suppress(CollectionCreateError):
            db.create_collection(_PIPELINE_EDGE_COLLECTION, edge=True)  # type: ignore[union-attr]
            logger.info("[V023] Created edge collection %s", _PIPELINE_EDGE_COLLECTION)

    if db.has_collection(_PIPELINE_EDGE_COLLECTION):
        edge_collection = db.collection(_PIPELINE_EDGE_COLLECTION)  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            edge_collection.add_persistent_index(fields=["_from", "_to"], unique=True)  # type: ignore[union-attr]
        with contextlib.suppress(IndexCreateError):
            edge_collection.add_persistent_index(fields=["_from"])  # type: ignore[union-attr]

    if not db.has_graph(_PIPELINE_GRAPH):  # type: ignore[union-attr]
        with contextlib.suppress(GraphCreateError):
            db.create_graph(  # type: ignore[union-attr]
                _PIPELINE_GRAPH,
                edge_definitions=[
                    {
                        "edge_collection": _PIPELINE_EDGE_COLLECTION,
                        "from_vertex_collections": ["libraries"],
                        "to_vertex_collections": [_PIPELINE_VERTEX_COLLECTION],
                    }
                ],
            )
            logger.info("[V023] Created graph %s", _PIPELINE_GRAPH)
    else:
        pipeline_graph = db.graph(_PIPELINE_GRAPH)  # type: ignore[union-attr]
        if pipeline_graph.has_edge_definition(_PIPELINE_EDGE_COLLECTION):
            with contextlib.suppress(EdgeDefinitionReplaceError):
                pipeline_graph.replace_edge_definition(
                    _PIPELINE_EDGE_COLLECTION,
                    ["libraries"],
                    [_PIPELINE_VERTEX_COLLECTION],
                )
                logger.info("[V023] Replaced edge definition for %s", _PIPELINE_EDGE_COLLECTION)
        else:
            with contextlib.suppress(EdgeDefinitionCreateError):
                pipeline_graph.create_edge_definition(
                    _PIPELINE_EDGE_COLLECTION,
                    ["libraries"],
                    [_PIPELINE_VERTEX_COLLECTION],
                )
                logger.info("[V023] Added edge definition for %s", _PIPELINE_EDGE_COLLECTION)

    if db.has_collection("libraries"):
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR lib IN libraries
                FILTER !HAS(lib, "library_auto_write")
                UPDATE lib WITH { library_auto_write: false } IN libraries
        """
        )
        logger.info("[V023] Ensured library_auto_write=false on existing libraries")

    required_collections = (
        "libraries",
        "library_contains_file",
        "file_has_state",
        _PIPELINE_EDGE_COLLECTION,
    )
    if not all(db.has_collection(name) for name in required_collections):  # type: ignore[union-attr]
        logger.info("[V023] Skipping initial pipeline state derivation because required collections are missing")
        return

    library_rows_cursor = cast(
        "Cursor",
        db.aql.execute(  # type: ignore[union-attr]
            """
        FOR lib IN libraries
            LET file_ids = (
                FOR file IN OUTBOUND lib._id library_contains_file
                    RETURN file._id
            )
            LET existing_state_edge = FIRST(
                FOR edge IN library_has_pipeline_state
                    FILTER edge._from == lib._id
                    LIMIT 1
                    RETURN edge._id
            )
            LET total_files = LENGTH(file_ids)
            LET tagged_count = LENGTH(
                FOR edge IN file_has_state
                    FILTER edge._from IN file_ids
                        AND edge._to == @tagged
                    RETURN 1
            )
            LET untagged_count = LENGTH(
                FOR edge IN file_has_state
                    FILTER edge._from IN file_ids
                        AND edge._to == @not_tagged
                    RETURN 1
            )
            LET calibrated_count = LENGTH(
                FOR edge IN file_has_state
                    FILTER edge._from IN file_ids
                        AND edge._to == @calibrated
                    RETURN 1
            )
            LET written_count = LENGTH(
                FOR edge IN file_has_state
                    FILTER edge._from IN file_ids
                        AND edge._to == @tags_written
                    RETURN 1
            )
            RETURN {
                library_id: lib._id,
                has_state_edge: existing_state_edge != null,
                total_files: total_files,
                tagged_count: tagged_count,
                untagged_count: untagged_count,
                calibrated_count: calibrated_count,
                written_count: written_count
            }
    """,
            bind_vars={
                "tagged": STATE_TAGGED,
                "not_tagged": STATE_NOT_TAGGED,
                "calibrated": STATE_CALIBRATED,
                "tags_written": STATE_TAGS_WRITTEN,
            },
        ),
    )
    library_rows = cast("list[dict[str, Any]]", list(library_rows_cursor))

    inserted_edges = 0
    for row in library_rows:
        if bool(row["has_state_edge"]):
            continue

        target_state = _derive_pipeline_state(
            total_files=int(row["total_files"]),
            tagged_count=int(row["tagged_count"]),
            untagged_count=int(row["untagged_count"]),
            calibrated_count=int(row["calibrated_count"]),
            written_count=int(row["written_count"]),
        )
        db.aql.execute(  # type: ignore[union-attr]
            """
            INSERT { _from: @library_id, _to: @target_state }
            INTO library_has_pipeline_state
            OPTIONS { ignoreErrors: true }
        """,
            bind_vars={
                "library_id": row["library_id"],
                "target_state": target_state,
            },
        )
        inserted_edges += 1

    logger.info("[V023] Ensured initial pipeline state edges for %s libraries", inserted_edges)
