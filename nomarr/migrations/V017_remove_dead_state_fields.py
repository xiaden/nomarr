"""V017: Remove dead flat state fields from library_files documents.

Background
----------
V016 introduced edge-based state management via ``file_has_state`` edges to
``file_states`` vertices.  All state queries and mutations now use the edge
model.  The flat fields on ``library_files`` documents are stale copies that
were kept during the V016 transition period.

This migration UNSETs the following fields from every ``library_files``
document:

**ML tagging (replaced by ml_tagged edge):**
- ``tagged`` (bool) — replaced by edge presence
- ``tagged_version`` (str) — now edge ``version`` attribute
- ``last_tagged_at`` (int) — now edge ``tagged_at`` attribute
- ``needs_tagging`` (bool) — replaced by edge absence
- ``tagging_skipped_reason`` (str) — encoded in edge ``version`` as ``scan_skipped``

**Calibration (replaced by calibrated edge):**
- ``calibration_hash`` (str) — now edge ``hash`` attribute

**Reconciliation (replaced by reconciled edge):**
- ``last_written_mode`` (str) — now edge ``mode`` attribute
- ``last_written_at`` (int) — now edge ``written_at`` attribute
- ``last_written_calibration_hash`` (str) — now edge ``calibration_hash`` attribute
- ``has_nomarr_namespace`` (bool) — now edge ``has_namespace`` attribute

**Scan validity (removed; invalid files are deleted):**
- ``is_valid`` (bool) — no replacement; invalid files are deleted on scan

Forward-only; no downgrade path.

All referenced code paths (``file_sync_comp``, ``tagging_writer_comp``,
``write_calibrated_tags_wf``, ``sync_file_to_library_wf``) have been migrated
to use edge-based state queries.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 16
SCHEMA_VERSION_AFTER: int = 17
DESCRIPTION: str = "Remove dead flat state fields from library_files"

_DEAD_FIELDS: list[str] = [
    # ML tagging
    "tagged",
    "tagged_version",
    "last_tagged_at",
    "needs_tagging",
    "tagging_skipped_reason",
    # Calibration
    "calibration_hash",
    # Reconciliation
    "last_written_mode",
    "last_written_at",
    "last_written_calibration_hash",
    "has_nomarr_namespace",
    # Scan validity
    "is_valid",
]


def upgrade(db: DatabaseLike) -> None:  # type: ignore[override]
    """Remove dead flat state fields from all library_files documents.

    Sets each dead field to ``null`` with ``keepNull: false``, which tells
    ArangoDB to remove the attribute from the document entirely.  Only
    documents that have at least one dead field are updated.

    Args:
        db: ArangoDB database handle.
    """
    # Build the null-setter object: { tagged: null, needs_tagging: null, ... }
    null_fields = ", ".join(f"{f}: null" for f in _DEAD_FIELDS)

    result = db.aql.execute(  # type: ignore[union-attr]
        f"""
        FOR file IN library_files
            FILTER file.tagged != null
                OR file.tagged_version != null
                OR file.needs_tagging != null
                OR file.is_valid != null
                OR file.calibration_hash != null
                OR file.last_written_mode != null
                OR file.last_written_at != null
                OR file.last_written_calibration_hash != null
                OR file.has_nomarr_namespace != null
                OR file.tagging_skipped_reason != null
                OR file.last_tagged_at != null
            UPDATE file WITH {{ {null_fields} }}
            IN library_files
            OPTIONS {{ keepNull: false }}
            COLLECT WITH COUNT INTO cnt
            RETURN cnt
        """,
    )
    count = next(result, 0)  # type: ignore[arg-type]
    logger.info(
        "Migration V017: Stripped %d dead state fields from %s library_files documents",
        len(_DEAD_FIELDS),
        count,
    )
