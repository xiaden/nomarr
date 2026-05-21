"""Binned analyze() and analyze_ctp() entrypoints."""

from __future__ import annotations

import contextlib as _contextlib
import logging as _logging
import time as _time
from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor
from concurrent.futures import as_completed as _as_completed

import numpy as _np
from tqdm import tqdm as _tqdm

from .. import db as _db
from ..similarity import l2_normalise as _l2_normalise
from ._cache import load_bin_stats as _load_bin_stats
from ._cache import load_norm_pair as _load_norm_pair
from ._constants import AGG_METHODS, REP_TYPES, SIM_METRICS, _EXPECTED_ROWS_PER_CONFIG
from ._process import _compute_song_stats, _process_group
from ._process import compute_agg_mats as _compute_agg_mats
from ._process import compute_retrieval_rows as _compute_retrieval_rows
from ._sim_cache import load_sim as _load_sim
from ._sim_cache import save_sim as _save_sim

try:
    from threadpoolctl import threadpool_limits as _threadpool_limits  # type: ignore[import]

    _HAS_THREADPOOLCTL = True
except Exception:
    _threadpool_limits = None  # type: ignore[assignment]
    _HAS_THREADPOOLCTL = False

_log = _logging.getLogger(__name__)


def analyze(
    con,
    *,
    k: int = 10,
    backbones: list[str] | None = None,
    workers: int = 6,
    blas_threads: int | None = None,
    song_ids: frozenset[str] | None = None,
) -> None:
    """Analyze missing binned retrieval configurations.

    Memory model (at n=2000 songs, bins=38, D=1280):
    - Loads only TWO normalised rep arrays per pair (≈780 MB) rather than all
      four simultaneously (was ≈3.1 GB).
    - Caches each [n×n] similarity matrix to
      ``{OUTPUT_ROOT}/sim_cache/…/{rep_a}_{rep_b}_{metric}.npz``.
    - On re-runs or same-corpus passes: cache hit → skip O(n²) computation
      entirely; only re-derive retrieval metrics (O(n log n)).
    - ``workers`` is kept in the signature for compatibility but is unused;
      BLAS parallelism handles the inner loop via OpenBLAS/MKL thread counts.
    """
    present = _db.query_binned_configs()
    done = _db.query_binned_analysis_done(con)
    done_configs = {(bb, mode, thresh) for bb, mode, thresh, *_rest in done if _rest[-1] == k}
    gap = present - done_configs
    if backbones is not None:
        wanted = set(backbones)
        gap = {cfg for cfg in gap if cfg[0] in wanted}

    if not gap:
        _log.info("[analyze] no incomplete binned configs found")
        return

    ctx = (
        _threadpool_limits(limits=blas_threads)
        if (blas_threads is not None and _HAS_THREADPOOLCTL)
        else _contextlib.nullcontext()
    )
    if blas_threads is not None and not _HAS_THREADPOOLCTL:
        _log.warning("[WARN] --blas-threads requested but threadpoolctl is unavailable; ignoring")

    with ctx:
        for backbone, bin_mode, std_thresh in sorted(gap):
            # --- Songs present in both DB and filesystem cache ---
            sids, artists = _db.load_sids_and_artists(con, backbone, bin_mode, std_thresh)
            if song_ids is not None:
                pairs = [(s, a) for s, a in zip(sids, artists) if s in song_ids]
                sids = [p[0] for p in pairs]
                artists = [p[1] for p in pairs]
            n_songs = len(sids)
            _log.info("[%s/%s thr=%.2f] n_songs=%d", backbone, bin_mode, std_thresh, n_songs)
            if n_songs < 2:
                _log.info("[%s/%s/%.2f] < 2 songs; skipping", backbone, bin_mode, std_thresh)
                continue

            # --- Metadata (small scalars, cheap) ---
            albums = _db.load_song_albums(con, sids)
            genres = _db.load_song_genres(con, sids)
            head_scores, head_names = _db.load_song_head_scores(con, backbone, sids)

            # --- Song stats (loads weights + mean vec only, no full rep arrays) ---
            bin_counts_list: list[int] = []
            for sid in sids:
                try:
                    stats_bins = _load_bin_stats(backbone, bin_mode, std_thresh, sid)
                    _compute_song_stats(sid, stats_bins, backbone, bin_mode, std_thresh, con)
                    bin_counts_list.append(len(stats_bins))
                except Exception as exc:
                    _log.warning(
                        "[%s/%s/%.2f] stats failed for %s: %s",
                        backbone, bin_mode, std_thresh, sid, exc,
                    )
                    bin_counts_list.append(0)
            bin_counts = _np.array(bin_counts_list, dtype=_np.float32)

            # --- Per-(rep_a, rep_b, metric) pair loop — one pair in memory at a time ---
            all_groups = [
                (rep_a, rep_b, metric)
                for rep_a in REP_TYPES
                for rep_b in REP_TYPES
                for metric in SIM_METRICS
            ]
            rows_all: list[tuple] = []
            per_head_rows_all: list[tuple] = []

            pair_bar = _tqdm(
                all_groups,
                leave=False,
                desc=f"[{backbone}/{bin_mode} thr={std_thresh:.2f}]",
            )
            for rep_a, rep_b, metric in pair_bar:
                pair_bar.set_postfix(pair=f"{rep_a}/{rep_b}/{metric}")

                # Check sim cache — skip expensive O(n²) computation on cache hit
                cached = _load_sim(backbone, bin_mode, std_thresh, rep_a, rep_b, metric)
                if cached is not None and cached[0] == sids:
                    _, agg_mats = cached
                    _log.debug(
                        "[%s/%s/%.2f] sim cache HIT %s_%s_%s",
                        backbone, bin_mode, std_thresh, rep_a, rep_b, metric,
                    )
                    # Skip metrics if DB rows already exist (delete DB to force recompute)
                    if _db.retrieval_rows_exist(con, backbone, bin_mode, std_thresh, rep_a, rep_b, metric):
                        del agg_mats
                        continue
                else:
                    # Load normalised vectors for only the two needed strategies
                    t0 = _time.perf_counter()
                    norm_a_all: list[_np.ndarray] = []
                    norm_b_all: list[_np.ndarray] = []
                    for sid in sids:
                        na, nb = _load_norm_pair(backbone, bin_mode, std_thresh, sid, rep_a, rep_b)
                        norm_a_all.append(na)
                        norm_b_all.append(nb)

                    inner_bar = _tqdm(total=n_songs, leave=False, desc=f"  {rep_a}/{rep_b}/{metric}")
                    agg_mats = _compute_agg_mats(
                        norm_a_all, norm_b_all, bin_counts, metric, progress=inner_bar,
                    )
                    inner_bar.close()
                    del norm_a_all, norm_b_all

                    _save_sim(backbone, bin_mode, std_thresh, rep_a, rep_b, metric, sids, agg_mats)
                    _log.debug(
                        "[%s/%s/%.2f] computed+saved %s_%s_%s  %.1fs",
                        backbone, bin_mode, std_thresh, rep_a, rep_b, metric,
                        _time.perf_counter() - t0,
                    )

                # Derive retrieval metrics (fast — O(n log n) argsort)
                new_rows, new_head_rows = _compute_retrieval_rows(
                    agg_mats, artists, backbone, bin_mode, std_thresh,
                    rep_a, rep_b, metric, k,
                    albums=albums, genres=genres,
                    head_scores=head_scores, head_names=head_names,
                )
                rows_all.extend(new_rows)
                per_head_rows_all.extend(new_head_rows)
                del agg_mats

            if rows_all:
                _log.info(
                    "[%s/%s thr=%.2f] writing %d retrieval rows ...",
                    backbone, bin_mode, std_thresh, len(rows_all),
                )
                _t_write = _time.perf_counter()
                _db.upsert_binned_retrieval_bulk(con, rows_all)
                _log.info(
                    "[%s/%s thr=%.2f] wrote %d/%d rows  (%.1fs)",
                    backbone, bin_mode, std_thresh, len(rows_all), _EXPECTED_ROWS_PER_CONFIG,
                    _time.perf_counter() - _t_write,
                )
            if per_head_rows_all:
                _db.upsert_head_sim_corr_batch(con, per_head_rows_all)
                _log.info(
                    "[%s/%s thr=%.2f] wrote %d per-head corr rows",
                    backbone, bin_mode, std_thresh, len(per_head_rows_all),
                )

            del sids, artists, albums, genres, head_scores, bin_counts
            del rows_all, per_head_rows_all


def analyze_ctp(
    con,
    *,
    k: int = 10,
    backbones: list[str] | None = None,
    workers: int = 6,
    blas_threads: int | None = None,
    song_ids: frozenset[str] | None = None,
) -> None:
    """Compute retrieval metrics for CTP-derived embedding pools (binned_ctp_vecs).

    CTP (Classifier-Then-Pool) segments are derived by STD-binning a head's score
    stream rather than the embedding-space distance. This function mirrors
    ``analyze()`` but iterates over (backbone, head, bin_mode, std_thresh) configs
    and stores results in ``binned_ctp_retrieval_rows`` for comparison against the
    PTC pathway results in ``binned_retrieval_rows``.
    """
    present = _db.query_ctp_configs(con)
    done = _db.query_ctp_analysis_done(con)
    done_configs = {(bb, hd, bm, thresh) for bb, hd, bm, thresh, kk in done if kk == k}
    gap = present - done_configs
    if backbones is not None:
        wanted = set(backbones)
        gap = {cfg for cfg in gap if cfg[0] in wanted}

    if not gap:
        _log.info("[analyze_ctp] no incomplete CTP configs found")
        return

    ctx = (
        _threadpool_limits(limits=blas_threads)
        if (blas_threads is not None and _HAS_THREADPOOLCTL)
        else _contextlib.nullcontext()
    )
    if blas_threads is not None and not _HAS_THREADPOOLCTL:
        _log.warning("[WARN] --blas-threads requested but threadpoolctl is unavailable; ignoring")

    with ctx:
        for backbone, head, bin_mode, std_thresh in sorted(gap):
            _log.info(
                "[%s|%s/%s thr=%.2f] Loading CTP vecs from DB ...",
                backbone, head, bin_mode, std_thresh,
            )
            _t_load = _time.perf_counter()
            sids, artists, song_data = _db.load_ctp_all_reps(
                con, backbone, head, bin_mode, std_thresh, song_ids=song_ids
            )
            n_songs = len(sids)
            _log.info(
                "[%s|%s/%s thr=%.2f] Loaded %d songs  (%.1fs)",
                backbone, head, bin_mode, std_thresh, n_songs, _time.perf_counter() - _t_load,
            )
            if n_songs < 2:
                _log.info("[%s|%s/%s/%.2f] < 2 songs; skipping", backbone, head, bin_mode, std_thresh)
                continue

            albums = _db.load_song_albums(con, sids)
            genres = _db.load_song_genres(con, sids)
            bin_counts = _np.array([len(sd) for sd in song_data], dtype=_np.float32)
            raw_reps: dict[str, list[_np.ndarray]] = {
                rep: [
                    _np.stack([b[f"vec_{rep}"] for b in song_data[idx]]).astype(_np.float32)
                    for idx in range(n_songs)
                ]
                for rep in REP_TYPES
            }
            norm_reps: dict[str, list[_np.ndarray]] = {
                rep: [_l2_normalise(raw_reps[rep][idx]) for idx in range(n_songs)]
                for rep in REP_TYPES
            }

            all_groups = [
                (rep_a, rep_b, metric)
                for rep_a in REP_TYPES
                for rep_b in REP_TYPES
                for metric in SIM_METRICS
            ]
            rows: list[tuple] = []
            progress = _tqdm(
                total=len(all_groups) * n_songs,
                leave=False,
                desc=f"[{backbone}|{head}/{bin_mode} thr={std_thresh:.2f}] ctp-groups",
            )
            try:
                with _ThreadPoolExecutor(max_workers=min(max(1, workers), len(all_groups))) as pool:
                    futures = {
                        pool.submit(
                            _process_group,
                            raw_reps[rep_a],
                            raw_reps[rep_b],
                            norm_reps[rep_a],
                            norm_reps[rep_b],
                            bin_counts,
                            artists,
                            rep_a,
                            rep_b,
                            metric,
                            backbone,
                            bin_mode,
                            std_thresh,
                            k,
                            progress,
                            albums,
                            genres,
                            None,   # head_scores — not meaningful here
                            None,   # head_names
                        ): (rep_a, rep_b, metric)
                        for rep_a, rep_b, metric in all_groups
                    }
                    for future in _as_completed(futures):
                        group_rows, _per_head = future.result()
                        # Insert `head` at position 1 to match binned_ctp_retrieval_rows PK order:
                        # (backbone, head, bin_mode, std_thresh, rep_a, rep_b, sim_metric, agg_method, k, ...)
                        for r in group_rows:
                            rows.append((r[0], head) + r[1:])
            finally:
                progress.close()

            if rows:
                _log.info(
                    "[%s|%s/%s thr=%.2f] Writing %d CTP retrieval rows ...",
                    backbone, head, bin_mode, std_thresh, len(rows),
                )
                _t_write = _time.perf_counter()
                _db.upsert_ctp_retrieval_bulk(con, rows)
                _log.info(
                    "[%s|%s/%s thr=%.2f] wrote %d rows  (%.1fs)",
                    backbone, head, bin_mode, std_thresh, len(rows),
                    _time.perf_counter() - _t_write,
                )
