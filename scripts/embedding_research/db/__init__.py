"""
DuckDB storage layer for the embedding research package.

Re-exports all public symbols from the db subpackage for backwards compatibility.
Callers using ``from .db import X`` or ``from . import db as _db; _db.X`` continue
to work without modification.

Submodules
----------
_schema         — DDL, connect(), ensure_schema()
songs           — songs table + song-level read helpers
flat            — head_results, analyze_metrics, song_retrieval_metrics (scalars + filesystem caches)
binned          — all binned_* tables
head_phase      — head_phase_provenance table + provenance helpers
queries         — query_* progress-check helpers
provenance      — run_provenance + corpus_state tables + read/write helpers
stream_registry — stream_registry / head_stream_registry low-level row CRUD
segmentation    — seg_config/seg_meta/seg_membership vocab + app-integrity guards
catalog_metadata — catalog_metadata singleton + read/update helpers
stratify        — stratified song sampling tables + helpers
truncation      — truncation-robustness table + helpers
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
from .binned import (
    load_binned_sampling_stats,
    load_calibration,
    load_classify_ctp_rows,
    query_classify_ctp_sids,
    upsert_binned_classify_ctp_bulk,
    upsert_binned_song_stats,
    upsert_calibration,
    upsert_head_sim_corr_batch,
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
    head_strategy_done,
    load_analyze_metrics,
    load_head_labels,
    upsert_head,
    write_analyze_metrics,
    write_song_retrieval_metrics,
)
from .head_phase import (
    HeadPhaseProvenanceRow,
    append_head_phase_archival_rows,
    build_archival_provenance_rows,
    build_head_phase_provenance_rows,
    head_phase_config_key,
    load_head_phase_provenance,
    load_head_phase_provenance_all,
    migrate_head_phase_provenance,
    query_head_phase_done,
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
    query_binned_classify_done,
    query_binned_configs,
    query_binned_embed_done,
    query_classify_done,
    query_head_sim_corr_done,
)
from .segmentation import (
    SegConfigNotFoundError,
    SegDuplicateConfigIdError,
    SegDuplicateMembershipRowError,
    SegDuplicateSegmentError,
    SegMemberIndexError,
    SegmentationError,
    SegOrphanError,
    SegStreamNotReadyError,
    SegValidationError,
    config_id_exists,
    config_row,
    raise_if_canonical_config_duplicate,
    raise_if_config_id_duplicate,
    raise_if_member_outside_verified_stream,
    raise_if_membership_duplicate,
    raise_if_orphan_membership,
    raise_if_orphan_seg_meta,
    raise_if_segment_duplicate,
    seg_config_columns,
    seg_config_logical_key_columns,
    seg_membership_columns,
    seg_meta_columns,
    seg_meta_exists,
)
from .songs import (
    load_all_songs,
    load_sids_and_artists,
    load_song_albums,
    load_song_genres,
    load_song_head_scores,
    song_exists,
    upsert_song,
)
from .stratify import clear_stale_stratification, load_stratified_sids, write_stratified_sids
from .stream_registry import (
    raise_if_head_duplicate,
    raise_if_stream_duplicate,
)
from .truncation import upsert_truncation_robustness

__all__ = [
    "LEGACY_RUN_ID",
    "REPAIR_GUIDANCE",
    "CanaryCorruptionError",
    "CanaryProbeReport",
    "CatalogMetadataCorruptionError",
    "CorpusStateCorruptionError",
    "HeadPhaseProvenanceRow",
    "SegConfigNotFoundError",
    "SegDuplicateConfigIdError",
    "SegDuplicateMembershipRowError",
    "SegDuplicateSegmentError",
    "SegMemberIndexError",
    "SegOrphanError",
    "SegStreamNotReadyError",
    "SegValidationError",
    "SegmentationError",
    "append_head_phase_archival_rows",
    "build_archival_provenance_rows",
    "build_head_phase_provenance_rows",
    "catalog_metadata_columns",
    "clear_song_retrieval_metrics",
    # connection / schema
    "clear_stale_stratification",
    "config_id_exists",
    "config_row",
    "connect",
    "corpus_state_columns",
    "detect_post_crash",
    "ensure_schema",
    "enumerate_pk_unique_tables",
    "head_phase_config_key",
    "head_strategy_done",
    "load_all_songs",
    "load_analyze_metrics",
    "load_binned_sampling_stats",
    "load_calibration",
    "load_classify_ctp_rows",
    "load_head_labels",
    "load_head_phase_provenance",
    "load_head_phase_provenance_all",
    "load_sids_and_artists",
    "load_song_albums",
    "load_song_genres",
    "load_song_head_scores",
    "load_stratified_sids",
    "migrate_analyze_metrics_provenance",
    "migrate_head_phase_provenance",
    "probe_table",
    "query_analysis_done",
    "query_binned_classify_done",
    "query_binned_configs",
    "query_binned_embed_done",
    "query_classify_ctp_sids",
    "query_classify_done",
    "query_head_phase_done",
    # progress queries
    "query_head_sim_corr_done",
    "raise_if_canonical_config_duplicate",
    "raise_if_config_id_duplicate",
    "raise_if_head_duplicate",
    "raise_if_member_outside_verified_stream",
    "raise_if_membership_duplicate",
    "raise_if_orphan_membership",
    "raise_if_orphan_seg_meta",
    "raise_if_segment_duplicate",
    "raise_if_stream_duplicate",
    "read_catalog_metadata",
    "read_corpus_state",
    "read_run_provenance",
    "require_supported_duckdb",
    "run_provenance_columns",
    "run_rollback_canary",
    "seg_config_columns",
    "seg_config_logical_key_columns",
    "seg_membership_columns",
    "seg_meta_columns",
    "seg_meta_exists",
    "song_exists",
    "storage_version_label",
    "update_catalog_metadata",
    "update_corpus_state",
    "upsert_binned_classify_ctp_bulk",
    "upsert_binned_song_stats",
    # binned pipeline
    "upsert_calibration",
    # flat pipeline
    "upsert_head",
    "upsert_head_sim_corr_batch",
    "upsert_phase_timing",
    # songs
    "upsert_song",
    "upsert_truncation_robustness",
    "write_analyze_metrics",
    "write_head_phase_provenance",
    "write_run_provenance",
    "write_song_retrieval_metrics",
    "write_stratified_sids",
]
