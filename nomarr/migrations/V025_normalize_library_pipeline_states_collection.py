"""V025: normalize library_pipeline_states into per-library documents."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any, cast

from arango.exceptions import IndexCreateError

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.5"
DESCRIPTION: str = "Normalize library_pipeline_states from singleton vertices to per-library documents"


def upgrade(db: DatabaseLike) -> None:
    """Convert pipeline state storage to constructor-friendly per-library documents."""
    if not db.has_collection("library_pipeline_states"):  # type: ignore[union-attr]
        logger.info("[V025] Skipping normalization because library_pipeline_states does not exist")
        return

    collection = db.collection("library_pipeline_states")  # type: ignore[union-attr]
    with contextlib.suppress(IndexCreateError):
        collection.add_persistent_index(fields=["library_key"], unique=True, sparse=True)  # type: ignore[union-attr]
    with contextlib.suppress(IndexCreateError):
        collection.add_persistent_index(fields=["pipeline_state"])  # type: ignore[union-attr]

    normalized_cursor = cast(
        "Cursor",
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN library_pipeline_states
                FILTER doc.library_key != null
                LIMIT 1
                RETURN 1
            """
        ),
    )
    already_normalized = next(normalized_cursor, None) is not None

    rows: list[dict[str, Any]] = []
    if not already_normalized and db.has_collection("library_has_pipeline_state"):  # type: ignore[union-attr]
        rows_cursor = cast(
            "Cursor",
            db.aql.execute(  # type: ignore[union-attr]
                """
                FOR edge IN library_has_pipeline_state
                    RETURN {
                        library_key: PARSE_IDENTIFIER(edge._from).key,
                        pipeline_state: edge._to
                    }
                """
            ),
        )
        rows = cast("list[dict[str, Any]]", list(rows_cursor))

    for row in rows:
        db.aql.execute(  # type: ignore[union-attr]
            """
            UPSERT { library_key: @library_key }
            INSERT { library_key: @library_key, pipeline_state: @pipeline_state }
            UPDATE { pipeline_state: @pipeline_state }
            IN library_pipeline_states
            """,
            bind_vars={
                "library_key": row["library_key"],
                "pipeline_state": row["pipeline_state"],
            },
        )

    legacy_ids_cursor = cast(
        "Cursor",
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN library_pipeline_states
                FILTER doc.library_key == null
                RETURN doc._id
            """
        ),
    )
    legacy_ids = cast("list[str]", list(legacy_ids_cursor))
    if legacy_ids:
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc_id IN @doc_ids
                REMOVE PARSE_IDENTIFIER(doc_id).key IN library_pipeline_states
            """,
            bind_vars={"doc_ids": legacy_ids},
        )

    logger.info(
        "[V025] Normalized library_pipeline_states: migrated %s edge-backed rows and removed %s legacy vertex docs",
        len(rows),
        len(legacy_ids),
    )
