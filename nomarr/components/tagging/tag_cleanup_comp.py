"""Tag cleanup helpers extracted from legacy tag persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _tags_ns(db: Database) -> Any:
    """Return the runtime-wired tags namespace with collection verbs attached."""
    return cast("Any", db.tags)


def _library_files_ns(db: Database) -> Any:
    """Return the runtime-wired library-files namespace with collection verbs attached."""
    return cast("Any", db.library_files)


def _song_has_tags_ns(db: Database) -> Any:
    """Return the runtime-wired song/tag edge namespace with collection verbs attached."""
    return cast("Any", db.song_has_tags)


def _tag_model_output_ns(db: Database) -> Any:
    """Return the runtime-wired tag/model-output edge namespace with collection verbs attached."""
    return cast("Any", db.tag_model_output)


def _get_orphaned_tag_ids(db: Database) -> set[str]:
    """Return tag ids that are unreferenced by song or model-output edges."""
    tags = _tags_ns(db)
    library_files = _library_files_ns(db)
    song_has_tags = _song_has_tags_ns(db)
    tag_model_output = _tag_model_output_ns(db)

    all_tag_ids = {
        str(tag_id)
        for row in cast("list[dict[str, Any]]", tags.aggregate("_id", limit=tags.count()))
        if (tag_id := row.get("value")) is not None
    }
    if not all_tag_ids:
        return set()

    song_edge_targets = {
        str(tag_id)
        for row in cast("list[dict[str, Any]]", library_files.aggregate("song_has_tags", limit=song_has_tags.count()))
        if (tag_id := row.get("value")) is not None
    }
    model_edge_sources = {
        str(tag_id)
        for row in cast("list[dict[str, Any]]", tag_model_output.aggregate("_from", limit=tag_model_output.count()))
        if (tag_id := row.get("value")) is not None
    }
    return all_tag_ids - song_edge_targets - model_edge_sources


def cleanup_orphaned_tags(db: Database) -> int:
    """Delete tag documents that have no song or model-output edges.

    The orphan scan is composed from constructor verbs and Python set difference,
    while deletion delegates to the schema-backed keyed cascade-delete path.
    """
    orphan_ids = _get_orphaned_tag_ids(db)
    if not orphan_ids:
        return 0
    tags = _tags_ns(db)
    deleted = 0
    for orphan_id in orphan_ids:
        orphan_key = orphan_id.split("/", 1)[1] if "/" in orphan_id else orphan_id
        deleted += int(tags.delete.cascade(_key=orphan_key))
    return deleted


def get_orphaned_tag_count(db: Database) -> int:
    """Count tags that currently have no song or model-output edges."""
    return len(_get_orphaned_tag_ids(db))
