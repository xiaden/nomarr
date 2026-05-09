"""V031: remove legacy state fields and indexes from library_files."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

MIGRATION_VERSION: str = "0.2.31"
DESCRIPTION: str = "Remove legacy state-ish library_files fields and obsolete indexes"

_LEGACY_LIBRARY_FILE_FIELDS = [
    "needs_tagging",
    "tagging_skipped_reason",
    "tagged",
    "tagged_version",
    "skip_auto_tag",
    "has_nomarr_namespace",
    "last_written_mode",
    "last_seen_scan_id",
    "write_claimed_by",
]

_LEGACY_INDEX_FIELDS = {
    ("library_id",),
    ("library_id", "path"),
    ("library_id", "normalized_path"),
    ("library_id", "tagged"),
    ("needs_tagging", "is_valid"),
    ("write_claimed_by",),
}


def _drop_legacy_indexes(db: DatabaseLike) -> None:
    coll = db.collection("library_files")  # type: ignore[union-attr]
    for idx in coll.indexes():  # type: ignore[union-attr]
        fields = tuple(idx.get("fields", []))
        if fields not in _LEGACY_INDEX_FIELDS:
            continue
        coll.delete_index(idx["id"])  # type: ignore[union-attr]
        logger.info("[V031] Dropped legacy library_files index %s", list(fields))


def _remove_legacy_fields(db: DatabaseLike) -> None:
    filter_expr = " OR ".join(f"HAS(doc, '{field_name}')" for field_name in _LEGACY_LIBRARY_FILE_FIELDS)
    null_patch = ", ".join(f"{field_name}: null" for field_name in _LEGACY_LIBRARY_FILE_FIELDS)
    db.aql.execute(  # type: ignore[union-attr]
        f"""
        FOR doc IN library_files
            FILTER {filter_expr}
            UPDATE doc WITH {{ {null_patch} }} IN library_files
            OPTIONS {{ keepNull: false }}
        """
    )
    logger.info("[V031] Removed legacy fields from library_files: %s", ", ".join(_LEGACY_LIBRARY_FILE_FIELDS))


def upgrade(db: DatabaseLike) -> None:
    """Drop obsolete indexes and remove legacy state-ish fields from ``library_files``."""
    _drop_legacy_indexes(db)
    _remove_legacy_fields(db)
