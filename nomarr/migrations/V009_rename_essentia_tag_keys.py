"""V009: Rename essentia-versioned tag keys to model-suite-versioned keys.

Background
----------
Prior to the ONNX migration (Parts A-C), numeric tag keys for ML predictions
used the runtime Essentia-TF version string as the "suite" component:

    nom:happy_essentia21b6dev1389_yamnet20210604_happy20220825
            ^^^^^^^^^^^^^^^^^^^^^  <- compact runtime version

This was fragile because every pip upgrade of essentia-tensorflow changed all
tag keys, effectively orphaning previously computed numeric tags in the DB.

Fix
---
The new key format uses a stable MODEL_SUITE_VERSION constant ("v1") that
only changes when the deployed model weights change, not when the inference
runtime changes (e.g. TF → ONNX):

    nom:happy_v1_yamnet20210604_happy20220825
            ^^  <- stable suite version

This migration:
  1. Finds all ``tags`` vertices whose ``rel`` field matches the old pattern
     ``nom:{label}_essentia{compact_version}_{rest}``.
  2. For each old tag vertex: UPSERTs a new tag vertex with the ``v1`` rel
     and the same scalar value.
  3. Redirects all ``song_tag_edges`` that pointed at the old vertex to
     point at the new vertex.
  4. Deletes the old tag vertices.

Idempotent: if a ``v1`` tag vertex already exists (same rel+value), the
UPSERT is a no-op and only the edge redirect + old vertex cleanup run.

Forward-only; no downgrade path.
Rollback documentation: to revert, run ``process_file_workflow`` on the
affected library — it will regenerate all keys with the current suite version.
Mood tags are unaffected (stored under ``nom:mood-strict`` etc.).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
SCHEMA_VERSION_BEFORE: int = 8
SCHEMA_VERSION_AFTER: int = 9
DESCRIPTION: str = (
    "Rename essentia-versioned numeric tag keys to model-suite-versioned keys (v1)"
)

# Matches the compact essentia version segment in a tag rel, e.g.
# "_essentia21b6dev1389_" in "nom:happy_essentia21b6dev1389_yamnet..."
_ESSENTIA_PATTERN = re.compile(r"_essentia[a-z0-9]+_")


def upgrade(db: DatabaseLike) -> None:  # type: ignore[override]
    """Rename all essentia-versioned tag vertices to model-suite v1 format.

    Steps:
    1. Discover all ``tags`` vertices with an essentia-versioned ``rel``.
    2. For each: compute the new ``rel``, UPSERT the new vertex, redirect
       edges, delete old vertex.

    Args:
        db: ArangoDB database handle.

    """
    logger.info("Migration V009: Scanning for essentia-versioned tag keys")

    # Step 1 — collect all candidate tag vertices
    cursor = db.aql.execute(  # type: ignore[union-attr]
        """
        FOR tag IN tags
            FILTER CONTAINS(tag.rel, "_essentia")
            RETURN { _id: tag._id, _key: tag._key, rel: tag.rel, value: tag.value }
        """
    )
    old_tags: list[dict] = list(cursor)  # type: ignore[arg-type]

    if not old_tags:
        logger.info("Migration V009: No essentia-versioned tags found — nothing to do")
        return

    # Filter using Python regex for precise matching (AQL REGEX_TEST is used as
    # a pre-filter; Python re confirms the exact pattern).
    candidates = [
        tag for tag in old_tags
        if _ESSENTIA_PATTERN.search(tag["rel"])
    ]

    if not candidates:
        logger.info("Migration V009: No tags matched the essentia pattern after filtering — nothing to do")
        return

    logger.info("Migration V009: Found %d tag vertices to rename", len(candidates))

    renamed = 0
    skipped = 0
    for tag in candidates:
        old_id: str = tag["_id"]
        old_rel: str = tag["rel"]
        value = tag["value"]

        new_rel = _ESSENTIA_PATTERN.sub("_v1_", old_rel)
        if new_rel == old_rel:
            # Regex matched CONTAINS pre-filter but not the sub() pattern — skip
            logger.warning("Migration V009: Could not rename rel '%s' — skipping", old_rel)
            skipped += 1
            continue

        # Step 2 — create/find the new tag vertex
        upsert_cursor = db.aql.execute(  # type: ignore[union-attr]
            """
            UPSERT { rel: @rel, value: @value }
            INSERT { rel: @rel, value: @value }
            UPDATE {}
            IN tags
            RETURN NEW._id != null ? NEW._id : (
                FOR t IN tags FILTER t.rel == @rel AND t.value == @value
                    LIMIT 1 RETURN t._id
            )[0]
            """,
            bind_vars={"rel": new_rel, "value": value},
        )
        new_id_result = list(upsert_cursor)  # type: ignore[arg-type]
        if not new_id_result or new_id_result[0] is None:
            # Fallback: query the vertex directly
            fallback_cursor = db.aql.execute(  # type: ignore[union-attr]
                "FOR t IN tags FILTER t.rel == @rel AND t.value == @value LIMIT 1 RETURN t._id",
                bind_vars={"rel": new_rel, "value": value},
            )
            fallback_result = list(fallback_cursor)  # type: ignore[arg-type]
            if not fallback_result:
                logger.error(
                    "Migration V009: Could not find or create new tag vertex for rel='%s', value=%r — skipping edge redirect",
                    new_rel, value,
                )
                skipped += 1
                continue
            new_id = str(fallback_result[0])
        else:
            new_id = str(new_id_result[0])

        # Step 3 — redirect all song_tag_edges that pointed at the old vertex
        db.aql.execute(  # type: ignore[union-attr]
            """
            FOR edge IN song_tag_edges
                FILTER edge._to == @old_id
                UPDATE edge WITH { _to: @new_id } IN song_tag_edges
            """,
            bind_vars={"old_id": old_id, "new_id": new_id},
        )

        # Step 4 — delete the old tag vertex
        db.aql.execute(  # type: ignore[union-attr]
            "REMOVE { _key: @key } IN tags",
            bind_vars={"key": tag["_key"]},
        )

        logger.debug("Migration V009: Renamed '%s' -> '%s'", old_rel, new_rel)
        renamed += 1

    logger.info(
        "Migration V009: Complete — renamed %d tag vertices, skipped %d",
        renamed,
        skipped,
    )
