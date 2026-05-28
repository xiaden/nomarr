"""
DuckDB storage layer for the embedding research package.

Re-exports all public symbols from the db subpackage for backwards compatibility.
Callers using ``from .db import X`` or ``from . import db as _db; _db.X`` continue
to work without modification.

Submodules
----------
_schema  — DDL, connect(), ensure_schema()
songs    — songs table + song-level read helpers
flat     — head_results, flat_head_labels, analyze_metrics  (scalars + filesystem caches)
binned   — all binned_* tables
patch    — patch_features table
queries  — query_* progress-check helpers
"""

from ._schema import connect, ensure_schema, upsert_phase_timing
from .binned import (
    load_binned_sampling_stats,
    load_calibration,
    load_classify_ctp_rows,
    query_classify_ctp_sids,
    upsert_binned_classify_ctp_bulk,
    upsert_binned_ptc_ctp_metrics,
    upsert_binned_song_stats,
    upsert_calibration,
    upsert_head_agreement,
    upsert_head_sim_corr_batch,
    upsert_ptc_ctp_metrics_bulk,
)
from .flat import (
    head_strategy_done,
    load_analyze_metrics,
    load_head_labels,
    query_flat_head_labels,
    upsert_flat_head_labels,
    upsert_head,
    write_analyze_metrics,
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
from .truncation import upsert_truncation_robustness

__all__ = [
    # connection / schema
    "connect",
    "ensure_schema",
    "head_strategy_done",
    "load_all_songs",
    "load_analyze_metrics",
    "load_binned_sampling_stats",
    "load_calibration",
    "load_classify_ctp_rows",
    "load_head_labels",
    "load_sids_and_artists",
    "load_song_albums",
    "load_song_genres",
    "load_song_head_scores",
    # patch features
    "patch_features_done",
    "query_analysis_done",
    "query_binned_classify_done",
    "query_binned_configs",
    "query_binned_embed_done",
    "query_classify_ctp_sids",
    "query_classify_done",
    "query_flat_head_labels",
    # progress queries
    "query_head_sim_corr_done",
    "song_exists",
    "upsert_binned_classify_ctp_bulk",
    "upsert_binned_ptc_ctp_metrics",
    "upsert_binned_song_stats",
    # binned pipeline
    "upsert_calibration",
    # flat pipeline
    "upsert_flat_head_labels",
    "upsert_head",
    "upsert_head_agreement",
    "upsert_head_sim_corr_batch",
    "upsert_phase_timing",
    "upsert_ptc_ctp_metrics_bulk",
    # songs
    "upsert_song",
    "upsert_truncation_robustness",
    "write_analyze_metrics",
]
