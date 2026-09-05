"""
DuckDB storage layer for the embedding research package.

Re-exports public symbols from the db subpackage so callers can import them directly
from ``scripts.embedding_research.db`` (``from .db import X`` or ``from . import db as _db;
_db.X``).

Submodules
----------
_schema         — DDL, connect(), ensure_schema()
analyze_scope   — analyze_metrics run-scope bookkeeping + catalog analyze writer
_types          — shared DB row DTO definitions
songs           — songs table + song-level read helpers
flat            — analyze_metrics + song_retrieval_metrics persistence
head_phase      — head_phase_provenance table + provenance helpers
queries         — query_* progress-check helpers
provenance      — run_provenance + corpus_state tables + read/write helpers
stream_registry — stream_registry / head_stream_registry low-level row CRUD
segmentation    — retained §B ready-row patch_count seam (P1-S12)
catalog_metadata — catalog_metadata singleton + read/update helpers
canary          — post-crash durability canary (dynamic PK/UNIQUE probe)
"""

from ._schema import (
    LEGACY_RUN_ID,
    connect,
    ensure_schema,
    migrate_analyze_metrics_provenance,
    require_supported_duckdb,
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
from .catalog_metadata import (
    CatalogMetadataCorruptionError,
    catalog_metadata_columns,
    read_catalog_metadata,
    update_catalog_metadata,
)
from .flat import (
    clear_song_retrieval_metrics,
    load_analyze_metrics,
    write_analyze_metrics,
    write_song_retrieval_metrics,
)
from .head_phase import (
    HeadPhaseProvenanceRow,
    build_head_phase_provenance_rows,
    head_phase_config_key,
    load_head_phase_provenance,
    write_head_phase_provenance,
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
from .segmentation import (
    SegmentationError,
    SegStreamNotReadyError,
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
    "LEGACY_RUN_ID",
    "REPAIR_GUIDANCE",
    "CanaryCorruptionError",
    "CanaryProbeReport",
    "CatalogMetadataCorruptionError",
    "CorpusStateCorruptionError",
    "HeadPhaseProvenanceRow",
    "SegStreamNotReadyError",
    "SegmentationError",
    "build_head_phase_provenance_rows",
    "catalog_metadata_columns",
    "clear_song_retrieval_metrics",
    "connect",
    "corpus_state_columns",
    "detect_post_crash",
    "ensure_schema",
    "enumerate_pk_unique_tables",
    "head_phase_config_key",
    "load_all_songs",
    "load_analyze_metrics",
    "load_head_phase_provenance",
    "migrate_analyze_metrics_provenance",
    "probe_table",
    "query_analysis_done",
    "raise_if_head_duplicate",
    "raise_if_stream_duplicate",
    "read_catalog_metadata",
    "read_corpus_state",
    "read_run_provenance",
    "require_supported_duckdb",
    "run_provenance_columns",
    "run_rollback_canary",
    "song_exists",
    "storage_version_label",
    "update_catalog_metadata",
    "update_corpus_state",
    "upsert_phase_timing",
    "upsert_song",
    "write_analyze_metrics",
    "write_head_phase_provenance",
    "write_run_provenance",
    "write_song_retrieval_metrics",
]
