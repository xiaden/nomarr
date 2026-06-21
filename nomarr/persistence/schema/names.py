"""Canonical collection name constants for the Nomarr schema.

Every collection name in ArangoDB is defined here exactly once.
All AQL operations, bootstrap, migrations, and components MUST reference
this enum instead of hardcoding collection name strings.
"""

from __future__ import annotations

from enum import StrEnum


class CollectionNames(StrEnum):
    """Every ArangoDB collection (document + edge) in the Nomarr schema.

    Document collections store entities (files, tags, libraries, settings).
    Edge collections store relationships (``_from`` → ``_to``).
    """

    # ── Document collections ──────────────────────────────────────────────
    LIBRARY_FILES = "library_files"
    LIBRARY_FOLDERS = "library_folders"
    LIBRARIES = "libraries"
    LIBRARY_SCANS = "library_scans"
    LIBRARY_PIPELINE_STATES = "library_pipeline_states"  # legacy, being phased out
    TAGS = "tags"
    FILE_STATES = "file_states"
    META = "meta"
    SESSIONS = "sessions"
    CALIBRATION_STATE = "calibration_state"
    CALIBRATION_HISTORY = "calibration_history"
    HEALTH = "health"
    WORKER_CLAIMS = "worker_claims"
    LOCKS = "locks"
    WORKER_RESTART_POLICY = "worker_restart_policy"
    ML_OUTPUT_STREAMS = "ml_output_streams"
    APPLIED_MIGRATIONS = "applied_migrations"
    VRAM_PROMISES = "vram_promises"
    ML_MODELS = "ml_models"
    ML_MODEL_OUTPUTS = "ml_model_outputs"
    NAVIDROME_TRACKS = "navidrome_tracks"
    NAVIDROME_PLAYCOUNTS = "navidrome_playcounts"
    ML_EMBEDDING_STREAMS = "ml_embedding_streams"

    # ── Edge collections ──────────────────────────────────────────────────
    SONG_HAS_TAGS = "song_has_tags"
    FILE_HAS_STATE = "file_has_state"
    FILE_HAS_OUTPUT_STREAM = "file_has_output_stream"
    OUTPUT_HAS_STREAM = "output_has_stream"
    HAS_ND_ID = "has_nd_id"
    HAS_PLAYS = "has_plays"
    LIBRARY_CONTAINS_FILE = "library_contains_file"
    LIBRARY_CONTAINS_FOLDER = "library_contains_folder"
    FILE_HAS_VECTORS = "file_has_vectors"
    FILE_HAS_EMBEDDING_STREAM = "file_has_embedding_stream"
    MODEL_HAS_OUTPUT = "model_has_output"
    MODEL_HAS_CALIBRATION = "model_has_calibration"
    LIBRARY_HAS_SCAN = "library_has_scan"
    LIBRARY_HAS_PIPELINE_STATE = "library_has_pipeline_state"  # legacy


__all__ = ["CollectionNames"]
