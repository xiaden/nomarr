"""Schema definition for the schema-driven persistence constructor.

This file is the single source of truth for all persistence collection schemas.
The SchemaConstructor reads this schema at import time to build namespace objects.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class CollectionType(StrEnum):
    """Types of ArangoDB collections."""

    DOCUMENT = "document"
    EDGE = "edge"
    STATE_GRAPH = "state_graph"
    TEMPLATE = "template"
    INFRASTRUCTURE = "infrastructure"


class SchemaValidationError(RuntimeError):
    """Raised at import time when SCHEMA contains invalid declarations."""


class CapabilityError(RuntimeError):
    """Raised when a namespace method is called without the required capability.

    Capability gating in the persistence constructor is enforced at call time,
    not by conditional attribute binding. Every method on a namespace is always
    present; calling a method whose capability is not declared in the schema
    raises this error with the offending collection/field/capability in the
    message. This makes the contract explicit, statically discoverable, and
    impossible to bypass via direct attribute access.
    """


# ---------------------------------------------------------------------------
# SCHEMA — the complete persistence API declaration
# ---------------------------------------------------------------------------
# Every collection the application uses MUST have an entry here.
# The SchemaConstructor reads this at import time and builds namespace objects.
#
# Schema structure per collection:
#   "collection_name": {
#       "type": CollectionType.DOCUMENT,
#       "capabilities": [...],        # collection-level verbs (insert, delete, cascade, etc.)
#       "fields": {
#           "field_name": {
#               "type": "str",        # Python type annotation string
#               "capabilities": [...], # field-level verbs (get, update, etc.)
#               "unique": True,       # optional — controls .get.one availability
#           },
#       },
#       "operators": {"get": ["in", "like"]},  # optional operator modifiers
#       "edges": {                    # edge collections from/to this collection
#           "edge_name": {"target": "target_collection", "direction": "OUTBOUND"},
#       },
#       "cascade": ["edge1", "edge2"],  # edges to walk on cascade verb
#   }
# ---------------------------------------------------------------------------

SCHEMA: dict[str, Any] = {
    # =========================================================================
    # INFRASTRUCTURE COLLECTIONS — minimal capabilities, key-value style
    # =========================================================================
    "meta": {
        "type": CollectionType.INFRASTRUCTURE,
        "capabilities": ["count"],
        "fields": {
            "key": {
                "type": "str",
                "capabilities": ["get", "upsert", "delete", "collect"],
                "unique": True,
            },
            "value": {
                "type": "str",
                "capabilities": ["get", "update"],
            },
        },
        "operators": {"get": ["in", "like"]},
    },
    "migrations": {
        "type": CollectionType.INFRASTRUCTURE,
        "collection_name": "applied_migrations",
        "capabilities": ["count"],
        "fields": {
            "name": {
                "type": "str",
                "capabilities": ["get", "upsert", "collect"],
                "unique": True,
            },
            "status": {
                "type": "str",
                "capabilities": ["get", "update"],
            },
            "applied_at": {
                "type": "str | None",
                "capabilities": ["get", "update"],
            },
            "started_at": {
                "type": "str",
                "capabilities": ["get"],
            },
            "migration_version": {
                "type": "str",
                "capabilities": ["get"],
            },
            "duration_ms": {
                "type": "int | None",
                "capabilities": ["get", "update"],
            },
        },
    },
    # =========================================================================
    # DOCUMENT COLLECTIONS — simple CRUD without cascade/traversal
    # =========================================================================
    "health": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get", "collect"], "unique": True},
            "component": {
                "type": "str",
                "capabilities": ["get", "upsert", "delete", "collect"],
                "unique": True,
            },
            "component_id": {
                "type": "str",
                "capabilities": ["get", "upsert", "update", "collect"],
                "unique": True,
            },
            "component_type": {
                "type": "str",
                "capabilities": ["get", "upsert", "collect"],
            },
            "status": {
                "type": "str",
                "capabilities": ["get", "upsert", "update", "collect", "aggregate"],
            },
            "message": {
                "type": "str | None",
                "capabilities": ["get", "upsert", "update"],
            },
            "last_heartbeat": {
                "type": "int",
                "capabilities": ["get", "upsert", "update"],
            },
            "current_job": {
                "type": "str | None",
                "capabilities": ["get", "upsert", "update"],
            },
            "metadata": {
                "type": "dict[str, Any] | None",
                "capabilities": ["get", "upsert", "update"],
            },
            "pid": {
                "type": "int | None",
                "capabilities": ["get", "upsert", "update"],
            },
            "exit_code": {
                "type": "int | None",
                "capabilities": ["get", "update"],
            },
            "restart_count": {
                "type": "int | None",
                "capabilities": ["get", "update"],
            },
            "last_restart": {
                "type": "int | None",
                "capabilities": ["get", "update"],
            },
            "error": {
                "type": "str | None",
                "capabilities": ["get", "update"],
            },
            "last_snapshot": {
                "type": "int | None",
                "capabilities": ["get", "update"],
            },
            "created_at": {
                "type": "int | None",
                "capabilities": ["get", "upsert"],
            },
            "snapshot_type": {
                "type": "str | None",
                "capabilities": ["get", "upsert", "collect"],
            },
        },
    },
    "sessions": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "session_id": {
                "type": "str",
                "capabilities": ["get", "upsert", "delete"],
                "unique": True,
            },
            "user_id": {
                "type": "str",
                "capabilities": ["get", "delete"],
            },
            "expiry_timestamp": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
        },
        "operators": {"get": ["in"]},
    },
    "locks": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            # document_reference is the field used for unique-constraint lock acquisition
            "document_reference": {
                "type": "str",
                "capabilities": ["get", "upsert", "delete"],
                "unique": True,
            },
            "lock_type": {
                "type": "str",
                "capabilities": ["get", "collect"],
            },
            "expires_at": {
                "type": "float",
                "capabilities": ["get", "update"],
            },
            "acquired_at": {
                "type": "float",
                "capabilities": ["get"],
            },
            "holder": {
                "type": "str",
                "capabilities": ["get"],
            },
            "status": {
                "type": "str",
                "capabilities": ["get", "update"],
            },
        },
        "operators": {"get": ["in"]},
    },
    "vram_promises": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "worker_id": {
                "type": "str",
                "capabilities": ["get", "delete", "collect"],
            },
            "pid": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
            "model_path": {
                "type": "str",
                "capabilities": ["get", "delete", "collect"],
            },
            "promised_mb": {
                "type": "float",
                "capabilities": ["get", "collect", "aggregate"],
            },
            "total_mb": {
                "type": "float",
                "capabilities": ["get", "update"],
            },
            "used_mb": {
                "type": "float",
                "capabilities": ["get", "update"],
            },
            "last_seen_ms": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
        },
    },
    "worker_claims": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "file_id": {
                "type": "str",
                "capabilities": ["get", "delete"],
                "unique": True,
            },
            "worker_id": {
                "type": "str",
                "capabilities": ["get", "delete", "collect"],
            },
            "claimed_at": {
                "type": "int",
                "capabilities": ["get"],
            },
            "claim_type": {
                "type": "str | None",
                "capabilities": ["get", "collect"],
            },
        },
    },
    "worker_restart_policy": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "upsert", "update", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "component_id": {
                "type": "str",
                "capabilities": ["get", "upsert", "update"],
                "unique": True,
            },
            "restart_count": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
            "last_restart_wall_ms": {
                "type": "int | None",
                "capabilities": ["get", "update"],
            },
            "failed_at_wall_ms": {
                "type": "int | None",
                "capabilities": ["get", "update"],
            },
            "failure_reason": {
                "type": "str | None",
                "capabilities": ["get", "update"],
            },
            "updated_at_wall_ms": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
        },
    },
    "ml_capacity": {
        "type": CollectionType.DOCUMENT,
        "collection_name": "ml_capacity_estimates",
        "capabilities": ["insert", "upsert", "update", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "model_set_hash": {
                "type": "str",
                "capabilities": ["get", "upsert", "delete"],
                "unique": True,
            },
            "measured_backbone_vram_mb": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
            "estimated_worker_ram_mb": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
            "probe_duration_s": {
                "type": "float",
                "capabilities": ["get", "update"],
            },
            "probed_by": {
                "type": "str",
                "capabilities": ["get", "update"],
            },
            "created_at": {
                "type": "int | None",
                "capabilities": ["get"],
            },
            "updated_at": {
                "type": "int | None",
                "capabilities": ["get", "update"],
            },
        },
    },
    "library_pipeline_states": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "upsert", "update", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "library_key": {
                "type": "str",
                "capabilities": ["get", "upsert", "update", "delete", "collect"],
                "unique": True,
            },
            "pipeline_state": {
                "type": "str",
                "capabilities": ["get", "update", "collect", "aggregate"],
            },
        },
        "edges": {
            "library_has_pipeline_state": {"target": "libraries", "direction": "INBOUND"},
        },
    },
    "library_scans": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "upsert", "update", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "library_key": {
                "type": "str",
                "capabilities": ["get", "update"],
                "unique": True,
            },
            "status": {
                "type": "str",
                "capabilities": ["get", "update", "collect"],
            },
            "files_processed": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
            "files_total": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
            "completed_at": {
                "type": "int | None",
                "capabilities": ["get", "update"],
            },
            "started_at": {
                "type": "int | None",
                "capabilities": ["get", "update"],
            },
            "error": {
                "type": "str | None",
                "capabilities": ["get", "update"],
            },
            "scan_type": {
                "type": "str | None",
                "capabilities": ["get", "update", "collect"],
            },
        },
        "edges": {
            "library_has_scan": {"target": "libraries", "direction": "INBOUND"},
        },
    },
    "library_folders": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "upsert", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "path": {
                "type": "str",
                "capabilities": ["get", "upsert"],
                "unique": True,
            },
            "library_key": {
                "type": "str",
                "capabilities": ["get", "collect"],
            },
        },
        "edges": {
            "library_contains_folder": {"target": "libraries", "direction": "INBOUND"},
        },
        "cascade": ["library_contains_folder"],
    },
    # =========================================================================
    # COMPLEX DOCUMENT COLLECTIONS — cascade, traversal, or special behavior
    # =========================================================================
    "libraries": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "delete", "cascade", "count", "traversal"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get", "collect"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get", "update", "collect"], "unique": True},
            "name": {
                "type": "str",
                "capabilities": ["get"],
                "unique": True,
            },
            "root_path": {
                "type": "str",
                "capabilities": ["get"],
                "unique": True,
            },
            "is_enabled": {"type": "bool", "capabilities": ["get", "collect"]},
            "watch_mode": {"type": "str", "capabilities": ["get", "collect"]},
            "file_write_mode": {"type": "str", "capabilities": ["get"]},
            "library_auto_write": {"type": "bool", "capabilities": ["get"]},
            "created_at": {"type": "int", "capabilities": ["get"]},
            "updated_at": {"type": "int", "capabilities": ["get"]},
            "vector_group_size": {"type": "int | None", "capabilities": ["get"]},
            "vector_search_thoroughness": {"type": "int | None", "capabilities": ["get"]},
        },
        "operators": {"get": ["in", "like"]},
        "edges": {
            "library_contains_file": {"target": "library_files", "direction": "OUTBOUND"},
            "library_contains_folder": {"target": "library_folders", "direction": "OUTBOUND"},
            "library_has_scan": {"target": "library_scans", "direction": "OUTBOUND"},
            "library_has_pipeline_state": {"target": "library_pipeline_states", "direction": "OUTBOUND"},
        },
        "cascade": [
            "library_contains_file",
            "library_contains_folder",
            "library_has_scan",
            "library_has_pipeline_state",
        ],
    },
    "library_files": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "upsert", "update", "delete", "cascade", "count", "traversal", "truncate"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get", "update"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get", "update", "collect"], "unique": True},
            "path": {
                "type": "str",
                "capabilities": ["get", "upsert", "update", "delete", "collect"],
                "unique": True,
            },
            "normalized_path": {
                "type": "str",
                "capabilities": ["get", "update", "collect"],
            },
            "library_key": {
                "type": "str",
                "capabilities": ["get", "count", "delete"],
            },
            "status": {"type": "str", "capabilities": ["get", "update"]},
            "modified_time": {"type": "int", "capabilities": ["get", "update"]},
            "duration_seconds": {"type": "float", "capabilities": ["get"]},
            "file_size": {"type": "int", "capabilities": ["get"]},
            "album": {"type": "str | None", "capabilities": ["get", "update", "aggregate"]},
            "title": {"type": "str | None", "capabilities": ["get", "update"]},
            "artist": {"type": "str | None", "capabilities": ["get", "update", "aggregate"]},
            "artists": {"type": "list[str] | None", "capabilities": ["get", "update"]},
            "labels": {"type": "list[str] | None", "capabilities": ["get", "update"]},
            "genres": {"type": "list[str] | None", "capabilities": ["get", "update"]},
            "year": {"type": "int | None", "capabilities": ["get", "update"]},
            "scanned_at": {"type": "int | None", "capabilities": ["get", "update"]},
            "chromaprint": {"type": "str | None", "capabilities": ["get", "update"]},
            "is_valid": {"type": "bool | None", "capabilities": ["get", "update"]},
            "last_tagged_at": {"type": "int | None", "capabilities": ["get", "update"]},
        },
        "operators": {"get": ["in", "like"]},
        "edges": {
            "song_has_tags": {"target": "tags", "direction": "OUTBOUND"},
            "file_has_state": {"target": "file_states", "direction": "OUTBOUND"},
            "file_has_vectors": {"target": "vectors_track", "direction": "OUTBOUND"},
            "file_has_segment_stats": {"target": "segment_scores_stats", "direction": "OUTBOUND"},
            "library_contains_file": {"target": "libraries", "direction": "INBOUND"},
        },
        "cascade": [
            "file_has_state",
            "song_has_tags",
            "file_has_vectors",
            "library_contains_file",
            "file_has_segment_stats",
        ],
    },
    "tags": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "delete", "cascade", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get", "collect"], "unique": True},
            "rel": {
                "type": "str",
                "capabilities": ["get", "count", "collect", "aggregate"],
            },
            "value": {
                "type": "str",
                "capabilities": ["get", "upsert"],
            },
        },
        "operators": {"get": ["in", "like"]},
        "edges": {
            "song_has_tags": {"target": "library_files", "direction": "INBOUND"},
            "tag_model_output": {"target": "ml_model_outputs", "direction": "OUTBOUND"},
        },
        "cascade": ["tag_model_output", "song_has_tags"],
    },
    "file_states": {
        # ADR-003: Boolean state graph — transition verb with three-phase READ→REMOVE→INSERT
        "type": CollectionType.STATE_GRAPH,
        "capabilities": ["count", "transition", "traversal"],
        "edge_collection": "file_has_state",
        "edges": {
            "file_has_state": {"target": "library_files", "direction": "INBOUND"},
        },
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
        },
    },
    "calibration_state": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "upsert", "update", "delete", "cascade", "count", "truncate"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get", "upsert"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get", "collect"], "unique": True},
            "head_name": {
                "type": "str",
                "capabilities": ["get", "upsert", "collect"],
            },
            "label": {
                "type": "str",
                "capabilities": ["get", "upsert", "collect"],
            },
            "calibration_def_hash": {
                "type": "str",
                "capabilities": ["get", "update"],
            },
            "histogram": {
                "type": "dict[str, Any]",
                "capabilities": ["get", "update"],
            },
            "histogram_bins": {
                "type": "list[dict[str, Any]] | None",
                "capabilities": ["get", "update"],
            },
            "p5": {
                "type": "float",
                "capabilities": ["get", "update"],
            },
            "p95": {
                "type": "float",
                "capabilities": ["get", "update"],
            },
            "n": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
            "underflow_count": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
            "overflow_count": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
            "updated_at": {
                "type": "int | None",
                "capabilities": ["get", "count"],
            },
        },
        "edges": {
            "model_has_calibration": {"target": "ml_models", "direction": "INBOUND"},
        },
        "cascade": ["model_has_calibration"],
    },
    "calibration_history": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "delete", "count", "truncate"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "calibration_key": {
                "type": "str",
                "capabilities": ["get", "delete"],
            },
            "snapshot_at": {
                "type": "int",
                "capabilities": ["get", "collect"],
            },
            "p5": {
                "type": "float",
                "capabilities": ["get"],
            },
            "p95": {
                "type": "float",
                "capabilities": ["get"],
            },
            "n": {
                "type": "int",
                "capabilities": ["get"],
            },
            "underflow_count": {
                "type": "int",
                "capabilities": ["get"],
            },
            "overflow_count": {
                "type": "int",
                "capabilities": ["get"],
            },
            "p5_delta": {
                "type": "float | None",
                "capabilities": ["get"],
            },
            "p95_delta": {
                "type": "float | None",
                "capabilities": ["get"],
            },
            "n_delta": {
                "type": "int | None",
                "capabilities": ["get"],
            },
        },
    },
    "ml_models": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "upsert", "update", "delete", "cascade", "count", "traversal"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get", "collect"], "unique": True},
            "path": {
                "type": "str",
                "capabilities": ["get", "upsert"],
                "unique": True,
            },
            "backbone": {
                "type": "str",
                "capabilities": ["get", "update", "collect"],
            },
            "head_type": {
                "type": "str",
                "capabilities": ["get", "update", "collect"],
            },
            "model_stem": {
                "type": "str",
                "capabilities": ["get", "update", "collect"],
            },
            "output_count": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
            "fully_configured": {
                "type": "bool",
                "capabilities": ["get", "update", "collect", "aggregate"],
            },
            "is_known": {
                "type": "bool",
                "capabilities": ["get", "update", "collect", "aggregate"],
            },
            "source": {
                "type": "str",
                "capabilities": ["get", "update", "collect"],
            },
            "head_release_date": {
                "type": "str",
                "capabilities": ["get", "update"],
            },
            "embedder_release_date": {
                "type": "str",
                "capabilities": ["get", "update"],
            },
            "registered_at": {
                "type": "int",
                "capabilities": ["get"],
            },
            "updated_at": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
        },
        "edges": {
            "model_has_output": {"target": "ml_model_outputs", "direction": "OUTBOUND"},
            "model_has_calibration": {"target": "calibration_state", "direction": "OUTBOUND"},
        },
        "cascade": ["model_has_output", "model_has_calibration"],
    },
    "ml_model_outputs": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "upsert", "update", "delete", "cascade", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get", "update"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "output_index": {
                "type": "int",
                "capabilities": ["get", "update", "collect"],
            },
            "label": {
                "type": "str | None",
                "capabilities": ["get", "update", "collect"],
            },
            "fully_labeled": {
                "type": "bool",
                "capabilities": ["get", "update", "collect", "aggregate"],
            },
        },
        "edges": {
            "model_has_output": {"target": "ml_models", "direction": "INBOUND"},
        },
        "cascade": ["model_has_output"],
    },
    "navidrome_tracks": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "upsert", "update", "delete", "cascade", "count", "traversal"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get", "upsert", "collect"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
        },
        "edges": {
            "has_nd_id": {"target": "library_files", "direction": "OUTBOUND"},
            "has_plays": {"target": "navidrome_playcounts", "direction": "OUTBOUND"},
        },
        "cascade": ["has_nd_id", "has_plays"],
    },
    "navidrome_playcounts": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "upsert", "update", "delete", "count", "traversal"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get", "upsert"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "playcount": {
                "type": "int",
                "capabilities": ["get", "upsert", "collect", "aggregate"],
            },
            "userid": {
                "type": "str",
                "capabilities": ["get", "upsert", "collect", "delete"],
            },
        },
        "edges": {
            "has_plays": {"target": "navidrome_tracks", "direction": "INBOUND"},
        },
    },
    "segment_scores_stats": {
        "type": CollectionType.DOCUMENT,
        "capabilities": ["insert", "upsert", "update", "delete", "cascade", "count", "truncate"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get", "upsert"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "head_name": {
                "type": "str",
                "capabilities": ["get", "update", "collect"],
            },
            "tagger_version": {
                "type": "str",
                "capabilities": ["get", "update", "collect"],
            },
            "num_segments": {
                "type": "int",
                "capabilities": ["get", "update", "aggregate"],
            },
            "pooling_strategy": {
                "type": "str",
                "capabilities": ["get", "update", "collect"],
            },
            "label_stats": {
                "type": "list[dict[str, Any]]",
                "capabilities": ["get", "update"],
            },
            "processed_at": {
                "type": "int",
                "capabilities": ["get", "update"],
            },
        },
        "edges": {
            "file_has_segment_stats": {"target": "library_files", "direction": "INBOUND"},
        },
        "cascade": ["file_has_segment_stats"],
    },
    # =========================================================================
    # EDGE COLLECTIONS — minimal capabilities, traversed via verb
    # =========================================================================
    "song_has_tags": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count", "truncate"],
        "fields": {
            "_from": {"type": "str", "capabilities": ["get", "delete"]},
            "_to": {"type": "str", "capabilities": ["get", "delete", "collect", "count", "upsert"]},
        },
    },
    "file_has_state": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_from": {"type": "str", "capabilities": ["get", "delete", "collect"]},
            "_to": {"type": "str", "capabilities": ["get", "collect"]},
        },
    },
    "tag_model_output": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get", "update"], "unique": True},
            "_id": {"type": "str", "capabilities": ["get"], "unique": True},
            "_from": {"type": "str", "capabilities": ["get", "delete", "collect"]},
            "_to": {"type": "str", "capabilities": ["get", "delete"]},
            "score": {"type": "float", "capabilities": ["get", "update"]},
            "created_at": {"type": "int", "capabilities": ["get"]},
            "updated_at": {"type": "int", "capabilities": ["get", "update"]},
        },
    },
    "library_contains_file": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_from": {"type": "str", "capabilities": ["get", "delete", "collect", "count"]},
            "_to": {"type": "str", "capabilities": ["get", "delete", "collect", "upsert"]},
        },
    },
    "library_contains_folder": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_from": {"type": "str", "capabilities": ["get"]},
            "_to": {"type": "str", "capabilities": ["get", "delete", "upsert"]},
        },
    },
    "library_has_scan": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_from": {"type": "str", "capabilities": ["get"]},
            "_to": {"type": "str", "capabilities": ["get", "delete", "upsert"]},
        },
    },
    "file_has_vectors": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_from": {"type": "str", "capabilities": ["get"]},
            "_to": {"type": "str", "capabilities": ["get", "delete"]},
        },
    },
    "file_has_segment_stats": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_from": {"type": "str", "capabilities": ["get"]},
            "_to": {"type": "str", "capabilities": ["get", "delete"]},
        },
    },
    "model_has_output": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get", "upsert"], "unique": True},
            "_from": {"type": "str", "capabilities": ["get"]},
            "_to": {"type": "str", "capabilities": ["get", "delete"]},
        },
    },
    "model_has_calibration": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_key": {"type": "str", "capabilities": ["get", "upsert"], "unique": True},
            "_from": {"type": "str", "capabilities": ["get"]},
            "_to": {"type": "str", "capabilities": ["get", "delete"]},
        },
    },
    "library_has_pipeline_state": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_from": {"type": "str", "capabilities": ["get"]},
            "_to": {"type": "str", "capabilities": ["get", "delete"]},
        },
    },
    "has_nd_id": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_from": {"type": "str", "capabilities": ["get"]},
            "_to": {"type": "str", "capabilities": ["get", "delete"]},
        },
    },
    "has_plays": {
        "type": CollectionType.EDGE,
        "capabilities": ["insert", "delete", "count"],
        "fields": {
            "_from": {"type": "str", "capabilities": ["get"]},
            "_to": {"type": "str", "capabilities": ["get", "delete"]},
            "last_played": {"type": "int", "capabilities": ["get"]},
        },
    },
    # =========================================================================
    # TEMPLATE COLLECTION — dynamic naming for vector collections
    # =========================================================================
    "vectors_track": {
        "type": CollectionType.TEMPLATE,
        "name_pattern": "vectors_track_{tier}__{backbone_id}__{library_key}",
        "collection_suffix": True,  # Supports optional __{suffix} for test/staging
        "capabilities": ["insert", "upsert", "update", "delete", "cascade", "count", "ann_search", "truncate"],
        "tiers": {
            "hot": {
                "fields": {
                    "_key": {"type": "str", "capabilities": ["get"], "unique": True},
                    "_id": {"type": "str", "capabilities": ["get", "collect"], "unique": True},
                    "file_id": {"type": "str", "capabilities": ["get", "delete"]},
                    "vector": {"type": "list[float]", "capabilities": ["get"]},
                },
            },
            "cold": {
                "fields": {
                    "_key": {"type": "str", "capabilities": ["get", "upsert"], "unique": True},
                    "_id": {"type": "str", "capabilities": ["get", "collect"], "unique": True},
                    "file_id": {"type": "str", "capabilities": ["get", "delete"]},
                    "vector": {"type": "list[float]", "capabilities": ["get"]},
                },
            },
        },
        "maintenance": {
            # Operations class that orchestrates across hot+cold collections
            "operates_on": ["hot", "cold"],
            "verbs": ["drain_to_cold", "rebuild_index", "get_stats"],
        },
    },
}
