"""DDL (Data Definition Language) for the Nomarr ArangoDB schema.

This module is the single source of truth for:
- Which collections exist and their types (document vs edge)
- Which indexes exist on each collection
- Which edge collections connect which vertex collections

``arango_bootstrap_comp.py`` and all migration code MUST use these
definitions rather than hardcoding collection or index names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .names import CollectionNames


class CollectionType(StrEnum):
    DOCUMENT = "document"
    EDGE = "edge"


@dataclass(frozen=True, slots=True)
class IndexDef:
    """Definition of a single ArangoDB index."""

    fields: list[str]
    index_type: str = "persistent"
    unique: bool = False
    sparse: bool = False
    expire_after: int | None = None


@dataclass(frozen=True, slots=True)
class CollectionDef:
    """Definition of a single ArangoDB collection."""

    name: CollectionNames
    collection_type: CollectionType
    indexes: list[IndexDef] = field(default_factory=list)
    description: str = ""


# ── Document collections ──────────────────────────────────────────────

DOCUMENT_COLLECTIONS: list[CollectionDef] = [
    CollectionDef(
        name=CollectionNames.META,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["key"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.LIBRARIES,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["is_enabled"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.LIBRARY_FILES,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["library_id"]),
            IndexDef(fields=["library_id", "path"], unique=True),
            IndexDef(fields=["library_id", "normalized_path"], unique=True),
            IndexDef(fields=["normalized_path"]),
            IndexDef(fields=["chromaprint"], sparse=True),
            IndexDef(fields=["needs_tagging", "is_valid"]),
            IndexDef(fields=["library_id", "tagged"]),
            IndexDef(fields=["path"]),
            IndexDef(fields=["calibration_hash"]),
            IndexDef(fields=["write_claimed_by"], sparse=True),
        ],
    ),
    CollectionDef(
        name=CollectionNames.LIBRARY_FOLDERS,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["library_id"]),
            IndexDef(fields=["library_id", "path"], unique=True),
        ],
    ),
    CollectionDef(
        name=CollectionNames.TAGS,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["name"]),
            IndexDef(fields=["name", "value"], unique=True),
        ],
    ),
    CollectionDef(
        name=CollectionNames.FILE_STATES,
        collection_type=CollectionType.DOCUMENT,
    ),
    CollectionDef(
        name=CollectionNames.SESSIONS,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["expiry_timestamp"], index_type="ttl", expire_after=0),
            IndexDef(fields=["session_id"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.CALIBRATION_STATE,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["calibration_def_hash"], unique=True),
            IndexDef(fields=["updated_at"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.CALIBRATION_HISTORY,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["calibration_key"]),
            IndexDef(fields=["snapshot_at"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.HEALTH,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["component_id"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.WORKER_CLAIMS,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["file_key"]),
            IndexDef(fields=["worker_id"]),
            IndexDef(fields=["claimed_at"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.LOCKS,
        collection_type=CollectionType.DOCUMENT,
    ),
    CollectionDef(
        name=CollectionNames.WORKER_RESTART_POLICY,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["component_id"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.ML_OUTPUT_STREAMS,
        collection_type=CollectionType.DOCUMENT,
    ),
    CollectionDef(
        name=CollectionNames.APPLIED_MIGRATIONS,
        collection_type=CollectionType.DOCUMENT,
    ),
    CollectionDef(
        name=CollectionNames.VRAM_PROMISES,
        collection_type=CollectionType.DOCUMENT,
    ),
    CollectionDef(
        name=CollectionNames.ML_MODELS,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["path"], unique=True),
        ],
    ),
    CollectionDef(
        name=CollectionNames.ML_MODEL_OUTPUTS,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["model_id", "output_index"], unique=True),
        ],
    ),
    CollectionDef(
        name=CollectionNames.NAVIDROME_TRACKS,
        collection_type=CollectionType.DOCUMENT,
    ),
    CollectionDef(
        name=CollectionNames.NAVIDROME_PLAYCOUNTS,
        collection_type=CollectionType.DOCUMENT,
        indexes=[
            IndexDef(fields=["userid", "playcount"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.ML_EMBEDDING_STREAMS,
        collection_type=CollectionType.DOCUMENT,
        description="Canonical int8 temporal embedding streams per (file, backbone)",
    ),
]

# ── Edge collections ──────────────────────────────────────────────────

EDGE_COLLECTIONS: list[CollectionDef] = [
    CollectionDef(
        name=CollectionNames.SONG_HAS_TAGS,
        collection_type=CollectionType.EDGE,
        indexes=[
            IndexDef(fields=["_from"]),
            IndexDef(fields=["_to"]),
            IndexDef(fields=["_from", "_to"], unique=True),
        ],
    ),
    CollectionDef(
        name=CollectionNames.FILE_HAS_STATE,
        collection_type=CollectionType.EDGE,
        indexes=[
            IndexDef(fields=["_from", "_to"], unique=True),
            IndexDef(fields=["_to"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.FILE_HAS_OUTPUT_STREAM,
        collection_type=CollectionType.EDGE,
        indexes=[
            IndexDef(fields=["_from"]),
            IndexDef(fields=["_to"]),
            IndexDef(fields=["_from", "_to"], unique=True),
        ],
    ),
    CollectionDef(
        name=CollectionNames.OUTPUT_HAS_STREAM,
        collection_type=CollectionType.EDGE,
        indexes=[
            IndexDef(fields=["_from"]),
            IndexDef(fields=["_to"]),
            IndexDef(fields=["_from", "_to"], unique=True),
        ],
    ),
    CollectionDef(
        name=CollectionNames.HAS_ND_ID,
        collection_type=CollectionType.EDGE,
        indexes=[
            IndexDef(fields=["_from", "_to"], unique=True),
            IndexDef(fields=["_to"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.HAS_PLAYS,
        collection_type=CollectionType.EDGE,
        indexes=[
            IndexDef(fields=["_from", "_to"], unique=True),
            IndexDef(fields=["_to"]),
        ],
    ),
    CollectionDef(
        name=CollectionNames.LIBRARY_CONTAINS_FILE,
        collection_type=CollectionType.EDGE,
    ),
    CollectionDef(
        name=CollectionNames.LIBRARY_CONTAINS_FOLDER,
        collection_type=CollectionType.EDGE,
    ),
    CollectionDef(
        name=CollectionNames.FILE_HAS_VECTORS,
        collection_type=CollectionType.EDGE,
    ),
    CollectionDef(
        name=CollectionNames.FILE_HAS_EMBEDDING_STREAM,
        collection_type=CollectionType.EDGE,
        indexes=[
            IndexDef(fields=["_from"]),
            IndexDef(fields=["_to"]),
            IndexDef(fields=["_from", "_to"], unique=True),
        ],
        description="Edge from library_files to ml_embedding_streams",
    ),
    CollectionDef(
        name=CollectionNames.MODEL_HAS_OUTPUT,
        collection_type=CollectionType.EDGE,
    ),
    CollectionDef(
        name=CollectionNames.MODEL_HAS_CALIBRATION,
        collection_type=CollectionType.EDGE,
    ),
]


# ── Combined list for bootstrap ───────────────────────────────────────

ALL_COLLECTIONS: list[CollectionDef] = DOCUMENT_COLLECTIONS + EDGE_COLLECTIONS


def collections_by_type(coll_type: CollectionType) -> list[CollectionDef]:
    """Return all collection definitions matching the given type."""
    return [c for c in ALL_COLLECTIONS if c.collection_type == coll_type]


def index_defs(collection: CollectionNames) -> list[IndexDef]:
    """Return the index definitions for a given collection."""
    for c in ALL_COLLECTIONS:
        if c.name == collection:
            return c.indexes
    return []


__all__ = [
    "ALL_COLLECTIONS",
    "DOCUMENT_COLLECTIONS",
    "EDGE_COLLECTIONS",
    "CollectionDef",
    "CollectionType",
    "IndexDef",
    "collections_by_type",
    "index_defs",
]
