"""Tag cleanup helpers extracted from legacy tag persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _get_orphaned_tag_ids(db: Database) -> set[str]:
    """Return tag ids that are unreferenced by song or model-output edges."""
    all_tag_ids = {str(tag_id) for tag_id in db.tags._id.collect(limit=db.tags.count())}
    if not all_tag_ids:
        return set()

    song_edge_targets = {str(tag_id) for tag_id in db.song_has_tags._to.collect(limit=db.song_has_tags.count())}
    model_edge_sources = {
        str(tag_id) for tag_id in db.tag_model_output._from.collect(limit=db.tag_model_output.count())
    }
    return all_tag_ids - song_edge_targets - model_edge_sources


def cleanup_orphaned_tags(db: Database) -> int:
    """Delete tag documents that have no song or model-output edges.

    The orphan scan is composed from constructor verbs and Python set difference,
    while deletion delegates to the schema-backed ``db.tags.cascade(...)`` path.
    """
    orphan_ids = _get_orphaned_tag_ids(db)
    if not orphan_ids:
        return 0
    return int(db.tags.cascade(list(orphan_ids)))


def get_orphaned_tag_count(db: Database) -> int:
    """Count tags that currently have no song or model-output edges."""
    return len(_get_orphaned_tag_ids(db))
