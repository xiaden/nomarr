"""V032: remove per-head float decision nom: tags, tag_model_output collection, and reset file tag-write states."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.32"
DESCRIPTION: str = (
    "Remove per-head float decision nom: tags, tag_model_output collection, and reset file tag-write states"
)
BATCH_SIZE: int = 500


def _collect_float_tag_ids(db: DatabaseLike) -> list[str]:
    cursor = db.aql.execute(  # type: ignore[union-attr]
        """
        FOR t IN tags
            FILTER STARTS_WITH(t.name, \"nom:\") AND IS_NUMBER(t.value)
            RETURN t._id
        """
    )
    tag_ids = list(cursor)  # type: ignore[arg-type]
    logger.info("[V032] Collected %s float nom: tag IDs", len(tag_ids))
    return tag_ids


def _delete_song_has_tags_edges(db: DatabaseLike, tag_ids: list[str]) -> None:
    if not tag_ids:
        logger.info("[V032] No float tag IDs found; skipping song_has_tags edge deletion")
        return

    total_deleted = 0
    for start in range(0, len(tag_ids), BATCH_SIZE):
        batch = tag_ids[start : start + BATCH_SIZE]
        cursor = db.aql.execute(  # type: ignore[union-attr]
            """
            FOR edge IN song_has_tags
                FILTER edge._to IN @tag_ids
                REMOVE edge IN song_has_tags
            """,
            bind_vars={"tag_ids": batch},
        )
        deleted = cursor.statistics().get("writesExecuted", 0)  # type: ignore[union-attr]
        total_deleted += deleted
        logger.info("[V032] Deleted %s song_has_tags edges for batch %s-%s", deleted, start, start + len(batch) - 1)
    logger.info("[V032] Deleted %s total song_has_tags edges", total_deleted)


def _delete_tag_vertices(db: DatabaseLike, tag_ids: list[str]) -> None:
    if not tag_ids:
        logger.info("[V032] No float tag IDs found; skipping tags vertex deletion")
        return

    total_deleted = 0
    for start in range(0, len(tag_ids), BATCH_SIZE):
        batch = tag_ids[start : start + BATCH_SIZE]
        cursor = db.aql.execute(  # type: ignore[union-attr]
            """
            FOR t IN tags
                FILTER t._id IN @tag_ids
                REMOVE t IN tags
            """,
            bind_vars={"tag_ids": batch},
        )
        deleted = cursor.statistics().get("writesExecuted", 0)  # type: ignore[union-attr]
        total_deleted += deleted
        logger.info("[V032] Deleted %s tag vertices for batch %s-%s", deleted, start, start + len(batch) - 1)
    logger.info("[V032] Deleted %s total tag vertices", total_deleted)


def _drop_tag_model_output_collection(db: DatabaseLike) -> None:
    if db.has_collection("tag_model_output"):  # type: ignore[union-attr]
        db.delete_collection("tag_model_output")  # type: ignore[union-attr]
        logger.info("[V032] Dropped tag_model_output collection")
        return
    logger.info("[V032] tag_model_output already absent, skipping")


def _reset_tag_write_states(db: DatabaseLike) -> None:
    cursor = db.aql.execute(  # type: ignore[union-attr]
        """
        FOR edge IN file_has_state
            FILTER edge._to == \"file_states/tags_written\"
            UPDATE edge WITH { _to: \"file_states/tags_not_written\" } IN file_has_state
        """
    )
    updated = cursor.statistics().get("writesExecuted", 0)  # type: ignore[union-attr]
    logger.info("[V032] Reset %s file tag-write states", updated)


def upgrade(db: DatabaseLike) -> None:
    """Remove float decision tags, their edges, legacy collection, and reset tag-write state edges."""
    logger.info("[V032] Collecting float nom: tag IDs")
    tag_ids = _collect_float_tag_ids(db)

    logger.info("[V032] Deleting song_has_tags edges for float nom: tags")
    _delete_song_has_tags_edges(db, tag_ids)

    logger.info("[V032] Deleting float nom: tag vertices")
    _delete_tag_vertices(db, tag_ids)

    logger.info("[V032] Dropping tag_model_output collection if present")
    _drop_tag_model_output_collection(db)

    logger.info("[V032] Resetting file tag-write states")
    _reset_tag_write_states(db)
