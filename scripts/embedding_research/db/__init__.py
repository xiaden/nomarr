"""
DuckDB storage layer for the embedding research package.

Re-exports all public symbols from the db subpackage for backwards compatibility.
Callers using ``from .db import X`` or ``from . import db as _db; _db.X`` continue
to work without modification.

Submodules
----------
_schema  — DDL, connect(), ensure_schema()
songs    — songs table + song-level read helpers
flat     — pooled_vecs, head_results, retrieval_rows, ann_rows, ptc_ctp_rows
binned   — all binned_* tables
patch    — patch_features table
queries  — query_* progress-check helpers
"""

from ._schema import connect, ensure_schema, upsert_phase_timing
from .binned import (
    binned_song_done,
    load_binned_all_reps,
    load_binned_head_decisions,
    load_binned_matrix,
    load_binned_sampling_stats,
    load_sids_and_artists,
    retrieval_rows_exist,
    query_ctp_analysis_done,
    query_ctp_configs,
    query_ctp_retrieval,
    query_head_sim_corr,
    upsert_binned_head,
    upsert_binned_pair_sims_bulk,
    upsert_binned_ptc_ctp_metrics,
    upsert_binned_retrieval,
    upsert_binned_retrieval_bulk,
    upsert_binned_song_stats,
    upsert_binned_vec,
    upsert_calibration,
    upsert_ctp_retrieval_bulk,
    upsert_head_agreement,
    upsert_head_sim_corr_batch,
    load_calibration,
    load_ctp_all_reps,
)
from .flat import (
    head_strategy_done,
    load_head_labels,
    load_pooled_matrix,
    load_retrieval_binned,
    load_retrieval_flat,
    pooled_exists,
    upsert_ann,
    upsert_head,
    upsert_pooled,
    upsert_ptc_ctp,
    upsert_retrieval,
)
from .patch import patch_features_done, upsert_patch_features
from .queries import (
    query_analysis_done,
    query_binned_analysis_done,
    query_binned_classify_done,
    query_binned_configs,
    query_binned_embed_done,
    query_classify_done,
    query_embedded_configs,
)
from .songs import (
    load_all_songs,
    load_song_albums,
    load_song_genres,
    load_song_head_scores,
    song_exists,
    upsert_song,
)

__all__ = [
    # connection / schema
    "connect",
    "ensure_schema",
    "upsert_phase_timing",
    # songs
    "upsert_song",
    "song_exists",
    "load_all_songs",
    "load_song_albums",
    "load_song_genres",
    "load_song_head_scores",
    # flat pipeline
    "upsert_pooled",
    "pooled_exists",
    "load_pooled_matrix",
    "upsert_head",
    "head_strategy_done",
    "load_head_labels",
    "upsert_retrieval",
    "load_retrieval_flat",
    "load_retrieval_binned",
    "upsert_ann",
    "upsert_ptc_ctp",
    # binned pipeline
    "upsert_calibration",
    "load_calibration",
    "upsert_binned_vec",
    "binned_song_done",
    "load_binned_matrix",
    "upsert_binned_head",
    "load_binned_head_decisions",
    "upsert_binned_retrieval",
    "upsert_binned_retrieval_bulk",
    "upsert_head_sim_corr_batch",
    "query_head_sim_corr",
    "upsert_head_agreement",
    "load_binned_all_reps",
    "load_binned_sampling_stats",
    "load_sids_and_artists",
    "retrieval_rows_exist",
    "upsert_binned_song_stats",
    "upsert_binned_pair_sims_bulk",
    "upsert_binned_ptc_ctp_metrics",
    # patch features
    "patch_features_done",
    "upsert_patch_features",
    # progress queries
    "query_embedded_configs",
    "query_analysis_done",
    "query_classify_done",
    "query_binned_embed_done",
    "query_binned_configs",
    "query_binned_analysis_done",
    "query_binned_classify_done",
]
