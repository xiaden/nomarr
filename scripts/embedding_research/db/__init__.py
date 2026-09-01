"""
DuckDB storage layer for the embedding research package.

Re-exports all public symbols from the db subpackage for backwards compatibility.
Callers using ``from .db import X`` or ``from . import db as _db; _db.X`` continue
to work without modification.

Submodules
----------
_schema    — DDL, connect(), ensure_schema()
songs      — songs table + song-level read helpers
flat       — head_results, analyze_metrics, song_retrieval_metrics  (scalars + filesystem caches)
binned     — all binned_* tables
patch      — patch_features table
head_phase — head_phase_provenance table + provenance helpers
queries    — query_* progress-check helpers
"""

from ._schema import connect, ensure_schema, upsert_phase_timing
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
    build_head_phase_provenance_rows,
    head_phase_config_key,
    load_head_phase_provenance,
    query_head_phase_done,
    write_head_phase_provenance,
)
from .patch import patch_features_done
from .queries import (
    query_analysis_done,
    query_binned_classify_done,
    query_binned_configs,
    query_binned_embed_done,
    query_classify_done,
    query_head_sim_corr_done,
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
from .truncation import upsert_truncation_robustness

__all__ = [
    "HeadPhaseProvenanceRow",
    "build_head_phase_provenance_rows",
    "clear_song_retrieval_metrics",
    # connection / schema
    "clear_stale_stratification",
    "connect",
    "ensure_schema",
    "head_phase_config_key",
    "head_strategy_done",
    "load_all_songs",
    "load_analyze_metrics",
    "load_binned_sampling_stats",
    "load_calibration",
    "load_classify_ctp_rows",
    "load_head_labels",
    "load_head_phase_provenance",
    "load_sids_and_artists",
    "load_song_albums",
    "load_song_genres",
    "load_song_head_scores",
    "load_stratified_sids",
    # patch features
    "patch_features_done",
    "query_analysis_done",
    "query_binned_classify_done",
    "query_binned_configs",
    "query_binned_embed_done",
    "query_classify_ctp_sids",
    "query_classify_done",
    "query_head_phase_done",
    # progress queries
    "query_head_sim_corr_done",
    "song_exists",
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
    "write_song_retrieval_metrics",
    "write_stratified_sids",
]
