"""
DuckDB storage layer for the embedding research package.

Re-exports public symbols from the db subpackage so callers can import them directly
from ``scripts.embedding_research.db`` (``from .db import X`` or ``from . import db as _db;
_db.X``).

Submodules
----------
_schema         — DDL, connect(), ensure_schema()
analyze_scope   — analyze_metrics run-scope bookkeeping
_types          — shared DB row DTO definitions
songs           — songs table + song-level read helpers
flat            — analyze_metrics + song_retrieval_metrics persistence
head_phase      — head_phase_provenance table + provenance helpers
incomplete_diagnostics - analyze_incomplete_diagnostics table + non-comparable diagnostics
queries         — query_* progress-check helpers
provenance      — run_provenance + corpus_state tables + read/write helpers
stream_registry — stream_registry / head_stream_registry low-level row CRUD
geometry        — exact-key per-song Gram geometry persistence
geometry_profile — pinned numerical execution profile
identity_persistence — geometry analysis/head evidence rows
result_surfaces — normalized class/baseline result surfaces + compact provenance
canary          — post-crash durability canary (dynamic PK/UNIQUE probe)
"""

from ._schema import (
    GEOMETRY_COLUMNS,
    GEOMETRY_TABLE,
    StaleSchemaError,
    connect,
    ensure_schema,
    require_supported_duckdb,
    schema_fingerprint,
    storage_version_label,
    upsert_phase_timing,
)
from .canary import (
    REPAIR_GUIDANCE,
    CanaryCorruptionError,
    CanaryProbeReport,
    detect_post_crash,
    enumerate_pk_unique_tables,
    probe_table,
    run_rollback_canary,
)
from .flat import (
    clear_song_retrieval_metrics,
    load_analyze_metrics,
    write_analyze_metrics,
    write_song_retrieval_metrics,
)
from .geometry import (
    INTEGRITY_REFUSED,
    MAX_GRAM_BYTES,
    MAX_PATCH_COUNT,
    STALE_REFUSED,
    GeometryIdentity,
    GeometryRecord,
    GeometryRefusal,
    IntegrityRefused,
    StaleRefused,
    enforce_geometry_resource_ceiling,
    observation_geometry_identity,
    preflight_geometry_binding,
    read_geometry,
    read_geometry_matrix,
    require_current_geometry,
    verify_geometry_binding,
    verify_geometry_current,
    write_geometry,
)

# Public geometry persistence API.
from .identity_persistence import (
    IdentityRefusal,
    read_evaluation_corpus,
    read_head_evidence,
    read_head_label_provenance,
    read_threshold_class_map,
    read_threshold_structural,
    write_evaluation_corpus,
    write_evaluation_corpus_in_transaction,
    write_head_evidence,
    write_head_label_provenance_in_transaction,
    write_threshold_class_map_in_transaction,
    write_threshold_structural_in_transaction,
)

__all__ = [
    "INTEGRITY_REFUSED",
    "MAX_GRAM_BYTES",
    "MAX_PATCH_COUNT",
    "STALE_REFUSED",
    "GeometryIdentity",
    "GeometryRecord",
    "GeometryRefusal",
    "IdentityRefusal",
    "IntegrityRefused",
    "StaleRefused",
    "enforce_geometry_resource_ceiling",
    "observation_geometry_identity",
    "preflight_geometry_binding",
    "read_geometry",
    "read_geometry_matrix",
    "read_head_evidence",
    "require_current_geometry",
    "verify_geometry_binding",
    "verify_geometry_current",
    "write_geometry",
    "write_head_evidence",
]
from .geometry_profile import (
    GEOMETRY_SEMANTICS_VERSION,
    GEOMETRY_SERIALIZATION_VERSION,
    NUMPY_KERNEL_VERSION,
    GeometryProfile,
    canonical_profile_json,
    profile_digest,
)
from .head_phase import (
    HeadPhaseProvenanceRow,
    build_head_phase_provenance_rows,
    head_phase_config_key,
    load_head_phase_provenance,
    write_head_phase_provenance,
)
from .incomplete_diagnostics import (
    DiagnosticError,
    incomplete_diagnostic_columns,
    read_incomplete_analyze_diagnostics,
    write_incomplete_analyze_diagnostic,
)
from .provenance import (
    CorpusStateCorruptionError,
    corpus_state_columns,
    read_corpus_state,
    read_run_provenance,
    run_provenance_columns,
    update_corpus_state,
    write_run_provenance,
)
from .queries import (
    query_analysis_done,
)
from .result_surfaces import (
    read_baseline_aggregate_metrics,
    read_baseline_neighborhoods,
    read_baseline_query_metrics,
    read_class_aggregate_metrics,
    read_class_neighborhoods,
    read_class_query_metrics,
    read_result_provenance,
    write_baseline_aggregate_metrics_in_transaction,
    write_baseline_neighborhoods_in_transaction,
    write_baseline_query_metrics_in_transaction,
    write_class_aggregate_metrics_in_transaction,
    write_class_neighborhoods_in_transaction,
    write_class_query_metrics_in_transaction,
    write_result_provenance_in_transaction,
)
from .songs import (
    load_all_songs,
    song_exists,
    upsert_song,
)
from .stream_registry import (
    raise_if_head_duplicate,
    raise_if_stream_duplicate,
)

__all__ = [
    "GEOMETRY_COLUMNS",
    "GEOMETRY_SEMANTICS_VERSION",
    "GEOMETRY_SERIALIZATION_VERSION",
    "GEOMETRY_TABLE",
    "NUMPY_KERNEL_VERSION",
    "REPAIR_GUIDANCE",
    "CanaryCorruptionError",
    "CanaryProbeReport",
    "CorpusStateCorruptionError",
    "DiagnosticError",
    "GeometryProfile",
    "HeadPhaseProvenanceRow",
    "IdentityRefusal",
    "StaleSchemaError",
    "build_head_phase_provenance_rows",
    "canonical_profile_json",
    "clear_song_retrieval_metrics",
    "connect",
    "corpus_state_columns",
    "detect_post_crash",
    "ensure_schema",
    "enumerate_pk_unique_tables",
    "head_phase_config_key",
    "incomplete_diagnostic_columns",
    "load_all_songs",
    "load_analyze_metrics",
    "load_head_phase_provenance",
    "probe_table",
    "profile_digest",
    "query_analysis_done",
    "raise_if_head_duplicate",
    "raise_if_stream_duplicate",
    "read_baseline_aggregate_metrics",
    "read_baseline_neighborhoods",
    "read_baseline_query_metrics",
    "read_class_aggregate_metrics",
    "read_class_neighborhoods",
    "read_class_query_metrics",
    "read_corpus_state",
    "read_evaluation_corpus",
    "read_head_evidence",
    "read_head_label_provenance",
    "read_incomplete_analyze_diagnostics",
    "read_result_provenance",
    "read_run_provenance",
    "read_threshold_class_map",
    "read_threshold_structural",
    "require_supported_duckdb",
    "run_provenance_columns",
    "run_rollback_canary",
    "schema_fingerprint",
    "song_exists",
    "storage_version_label",
    "update_corpus_state",
    "upsert_phase_timing",
    "upsert_song",
    "write_analyze_metrics",
    "write_baseline_aggregate_metrics_in_transaction",
    "write_baseline_neighborhoods_in_transaction",
    "write_baseline_query_metrics_in_transaction",
    "write_class_aggregate_metrics_in_transaction",
    "write_class_neighborhoods_in_transaction",
    "write_class_query_metrics_in_transaction",
    "write_evaluation_corpus",
    "write_evaluation_corpus_in_transaction",
    "write_head_evidence",
    "write_head_label_provenance_in_transaction",
    "write_head_phase_provenance",
    "write_incomplete_analyze_diagnostic",
    "write_result_provenance_in_transaction",
    "write_run_provenance",
    "write_song_retrieval_metrics",
    "write_threshold_class_map_in_transaction",
    "write_threshold_structural_in_transaction",
]
