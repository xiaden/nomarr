"""Golden section search for optimal dist_threshold.

Evaluates disc_artist (or configured objective) in-memory on a random subsample
of songs.  No cache files are written during optimization — all evaluation is
done purely in memory.

Entry point
-----------
    from scripts.embedding_research.strategy_binned._optimize import optimize_std_threshold

    optimal_k = optimize_std_threshold(
        con,
        backbone="effnet",
        bin_mode="temporal_global",
        song_ids=cfg["song_ids"],
        k=cfg["k"],
        objective="disc_artist",
        search_range=(0.1, 1.2),
        subsample_size=200,
        tolerance=0.05,
        max_evals=15,
    )

The function returns the optimal ``dist_thresh`` value found.  The caller is
responsible for using that value (e.g. by patching
``scripts.embedding_research.helpers.binning.DIST_THRESHOLDS`` before running
embed).
"""

from __future__ import annotations

import csv
import hashlib
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from scripts.embedding_research import db as _db
from scripts.embedding_research.config import OUTPUT_ROOT as _OUTPUT_ROOT
from scripts.embedding_research.config import patches_path as _patches_path
from scripts.embedding_research.helpers.binning import DIST_FNS as _DIST_FNS
from scripts.embedding_research.helpers.binning import canonical_threshold as _canonical_threshold
from scripts.embedding_research.helpers.binning import temporal_global_equivalents as _temporal_global_equivalents
from scripts.embedding_research.helpers.binning import temporal_segment_with_diagnostics
from scripts.embedding_research.helpers.binning import threshold_key as _threshold_key
from scripts.embedding_research.strategy_binned._constants import AGG_METHODS as _AGG_METHODS
from scripts.embedding_research.strategy_binned._constants import SIM_METRICS as _SIM_METRICS
from scripts.embedding_research.strategy_binned._pool import _pool_segment
from scripts.embedding_research.strategy_binned._process import (
    compute_agg_mats,
    compute_retrieval_rows,
)
from scripts.embedding_research.vector_types import RawTensor, UnitTensor

_log = logging.getLogger(__name__)

_PHI = (1 + 5**0.5) / 2  # golden ratio ≈ 1.618
_RESPHI = 2 - _PHI  # ≈ 0.382


@dataclass(frozen=True)
class OptimizationResult:
    """Best optimizer result for one (backbone, bin_mode) evaluation."""

    threshold: float
    score: float


def _build_grid(search_range: tuple[float, float], step: float = 0.05) -> list[float]:
    lo = _canonical_threshold(search_range[0])
    hi = _canonical_threshold(search_range[1])
    if hi <= lo:
        return [lo]
    out: list[float] = []
    x = lo
    while x <= hi + 1e-9:
        out.append(_canonical_threshold(x))
        x += step
    return sorted(set(out))


# ---------------------------------------------------------------------------
# Internal helpers


def _golden_section_max(
    f: Callable[[float], float],
    a: float,
    b: float,
    *,
    tol: float = 0.05,
    max_evals: int = 15,
) -> tuple[float, float, int]:
    """Golden section search for maximum of unimodal f on [a, b].

    Returns (optimal_x, f(optimal_x), n_evals).
    """
    x1 = a + _RESPHI * (b - a)
    x2 = b - _RESPHI * (b - a)
    f1 = f(x1)
    f2 = f(x2)
    n_evals = 2
    _log.info(
        "[optimize] GSS init  a=%.3f x1=%.3f(f=%.4f) x2=%.3f(f=%.4f) b=%.3f",
        a,
        x1,
        f1,
        x2,
        f2,
        b,
    )

    while (b - a) > tol and n_evals < max_evals:
        if f1 < f2:
            # Maximum is in [x1, b] — discard [a, x1]
            a = x1
            x1 = x2
            f1 = f2
            x2 = b - _RESPHI * (b - a)
            f2 = f(x2)
        else:
            # Maximum is in [a, x2] — discard [x2, b]
            b = x2
            x2 = x1
            f2 = f1
            x1 = a + _RESPHI * (b - a)
            f1 = f(x1)
        n_evals += 1
        _log.info(
            "[optimize] GSS step %d  interval=[%.3f, %.3f] width=%.3f  best=%.4f",
            n_evals,
            a,
            b,
            b - a,
            max(f1, f2),
        )

    if f1 >= f2:
        return x1, f1, n_evals
    return x2, f2, n_evals


_SongEntry = tuple[str, str, str | None, str | None, np.ndarray]
"""
(sid, artist, album, genre, raw_f32[n_patches, D])
"""


def _eval_threshold(
    dist_thresh: float,
    *,
    backbone: str,
    bin_mode: str,
    song_data: list[_SongEntry],
    objective: str,
    k: int,
    rep_type: str,
    agg_method: str,
    metric: str,
    head_scores_by_sid: dict[str, np.ndarray] | None = None,
    head_names: list[str] | None = None,
) -> tuple[float, dict, dict[str, tuple[tuple[int, ...], ...]]]:
    """Evaluate objective disc metric at a given dist_thresh in memory.

    Parameters
    ----------
    song_data:
        List of ``(sid, artist, album, genre, raw_patches_f32)``
        tuples, pre-loaded from sidecar files.  Songs with < 2 patches are
        excluded by the caller.
    objective:
        Column name on ``BinnedRetrievalRow``: ``disc_artist``,
        ``disc_genre``, or ``disc_general``.

    Returns
    -------
    float
        Mean objective score across rows, or 0.0 if evaluation fails.
    """
    threshold = dist_thresh  # direct cosine/Chebyshev distance value

    dist_fn = _DIST_FNS[bin_mode]

    norm_vecs: list[UnitTensor] = []
    artists: list[str] = []
    albums: list[str] = []
    genres: list[str] = []
    eval_sids: list[str] = []
    bin_counts: list[int] = []
    bin_lengths: list[int] = []
    one_bin_song_count = 0
    single_segment_bins = 0
    layouts: dict[str, tuple[tuple[int, ...], ...]] = {}
    diag_counters = {
        "distance_boundary_count": 0,
        "absorbed_outlier_count": 0,
        "hard_split_count": 0,
        "return_from_outlier_count": 0,
    }

    for sid, artist, album, genre, raw_f32 in song_data:
        raw_t = RawTensor(raw_f32)
        unit_t = raw_t.normalize()  # row-normalizes; .norm captures original row magnitudes

        segments, seg_diag = temporal_segment_with_diagnostics(
            unit_t.data,
            threshold,
            dist_fn,
        )
        if not segments:
            continue

        layout = tuple(tuple(int(i) for i in seg["indices"]) for seg in segments)
        layouts[sid] = layout
        for key in diag_counters:
            diag_counters[key] += int(seg_diag.get(key, 0))
        if len(segments) == 1:
            one_bin_song_count += 1
        for seg in segments:
            seg_len = len(seg["indices"])
            bin_lengths.append(seg_len)
            if seg_len == 1:
                single_segment_bins += 1

        pooled_norms: list[np.ndarray] = []
        for seg in segments:
            p = _pool_segment(raw_t, unit_t, seg["indices"])
            if rep_type not in p:
                raise ValueError(f"Optimizer rep_type={rep_type!r} not available in pooled payload")
            pooled_norms.append(p[rep_type]["vec_norm"].data)

        if not pooled_norms:
            continue

        stacked = np.stack(pooled_norms, axis=0).astype(np.float32)  # [n_bins, D], already unit
        ut = UnitTensor._from_unit(stacked, np.ones(len(pooled_norms), dtype=np.float32))

        norm_vecs.append(ut)
        eval_sids.append(sid)
        artists.append(artist)
        albums.append(album or "unknown")
        genres.append(genre or "unknown")
        bin_counts.append(len(pooled_norms))

    n = len(norm_vecs)
    if n < 4:
        _log.info("[optimize] dist_thresh=%.3f  n_valid=%d  (too few songs → 0.0)", dist_thresh, n)
        return (
            0.0,
            {
                "songs_evaluated": n,
                "total_bins": int(sum(bin_counts)) if bin_counts else 0,
                "mean_bins_per_song": float(np.mean(np.asarray(bin_counts, dtype=np.float32))) if bin_counts else 0.0,
                "median_bins_per_song": float(np.median(np.asarray(bin_counts, dtype=np.float32)))
                if bin_counts
                else 0.0,
                "p05_bins_per_song": float(np.percentile(np.asarray(bin_counts, dtype=np.float32), 5))
                if bin_counts
                else 0.0,
                "p95_bins_per_song": float(np.percentile(np.asarray(bin_counts, dtype=np.float32), 95))
                if bin_counts
                else 0.0,
                "min_bins_per_song": int(min(bin_counts)) if bin_counts else 0,
                "max_bins_per_song": int(max(bin_counts)) if bin_counts else 0,
                "mean_bin_len_segments": float(np.mean(np.asarray(bin_lengths, dtype=np.float32)))
                if bin_lengths
                else 0.0,
                "median_bin_len_segments": float(np.median(np.asarray(bin_lengths, dtype=np.float32)))
                if bin_lengths
                else 0.0,
                "p05_bin_len_segments": float(np.percentile(np.asarray(bin_lengths, dtype=np.float32), 5))
                if bin_lengths
                else 0.0,
                "p95_bin_len_segments": float(np.percentile(np.asarray(bin_lengths, dtype=np.float32), 95))
                if bin_lengths
                else 0.0,
                "single_segment_bins": single_segment_bins,
                "one_bin_song_count": one_bin_song_count,
                "one_bin_song_frac": float(one_bin_song_count / n) if n else 0.0,
                "distance_boundary_count": diag_counters["distance_boundary_count"],
                "absorbed_outlier_count": diag_counters["absorbed_outlier_count"],
                "hard_split_count": diag_counters["hard_split_count"],
                "return_from_outlier_count": diag_counters["return_from_outlier_count"],
                "no_split_count": one_bin_song_count,
                "disc_artist": 0.0,
                "disc_genre": 0.0,
                "disc_head": 0.0,
                "disc_general": 0.0,
                "map_k": 0.0,
                "mrr": 0.0,
                "ndcg_k": 0.0,
                "recall_k": 0.0,
                "sim_checksum": "",
            },
            layouts,
        )

    bc_arr = np.array(bin_counts, dtype=np.float32)
    head_scores_aligned: np.ndarray | None = None
    if head_scores_by_sid is not None and head_names:
        neutral = np.full((len(head_names),), 0.5, dtype=np.float32)
        head_scores_aligned = np.stack(
            [head_scores_by_sid.get(sid, neutral) for sid in eval_sids],
            axis=0,
        ).astype(np.float32)

    agg_mats = compute_agg_mats(norm_vecs, norm_vecs, bc_arr, metric)
    rows, _ = compute_retrieval_rows(
        agg_mats,
        artists,
        backbone,
        bin_mode,
        dist_thresh,
        rep_type,
        rep_type,
        metric,
        k,
        n,
        albums=albums,
        genres=genres,
        head_scores=head_scores_aligned,
        head_names=head_names,
    )

    scores: list[float] = []
    for row in rows:
        if row.agg_method != agg_method:
            continue
        v = getattr(row, objective, None)
        if v is not None and isinstance(v, float) and not np.isnan(v):
            scores.append(v)

    result = float(np.mean(scores)) if scores else 0.0
    disc_artist_vals = [float(r.disc_artist) for r in rows if r.disc_artist is not None]
    disc_genre_vals = [float(r.disc_genre) for r in rows if r.disc_genre is not None]
    disc_head_vals = [float(r.disc_head) for r in rows if r.disc_head is not None]
    disc_general_vals = [float(r.disc_general) for r in rows if r.disc_general is not None]
    map_vals = [float(r.map_k) for r in rows if r.map_k is not None]
    mrr_vals = [float(r.mrr) for r in rows if r.mrr is not None]
    ndcg_vals = [float(r.ndcg_k) for r in rows if r.ndcg_k is not None]
    recall_vals = [float(r.recall_k) for r in rows if r.recall_k is not None]
    sim_checksum = hashlib.blake2b(
        np.ascontiguousarray(agg_mats[agg_method]).view(np.uint8),
        digest_size=12,
    ).hexdigest()

    diag = {
        "songs_evaluated": n,
        "total_bins": int(sum(bin_counts)) if bin_counts else 0,
        "mean_bins_per_song": float(np.mean(bc_arr)) if len(bc_arr) else 0.0,
        "median_bins_per_song": float(np.median(bc_arr)) if len(bc_arr) else 0.0,
        "p05_bins_per_song": float(np.percentile(bc_arr, 5)) if len(bc_arr) else 0.0,
        "p95_bins_per_song": float(np.percentile(bc_arr, 95)) if len(bc_arr) else 0.0,
        "min_bins_per_song": int(min(bin_counts)) if bin_counts else 0,
        "max_bins_per_song": int(max(bin_counts)) if bin_counts else 0,
        "mean_bin_len_segments": float(np.mean(np.asarray(bin_lengths, dtype=np.float32))) if bin_lengths else 0.0,
        "median_bin_len_segments": float(np.median(np.asarray(bin_lengths, dtype=np.float32))) if bin_lengths else 0.0,
        "p05_bin_len_segments": float(np.percentile(np.asarray(bin_lengths, dtype=np.float32), 5))
        if bin_lengths
        else 0.0,
        "p95_bin_len_segments": float(np.percentile(np.asarray(bin_lengths, dtype=np.float32), 95))
        if bin_lengths
        else 0.0,
        "single_segment_bins": single_segment_bins,
        "one_bin_song_count": one_bin_song_count,
        "one_bin_song_frac": float(one_bin_song_count / n) if n else 0.0,
        "distance_boundary_count": diag_counters["distance_boundary_count"],
        "absorbed_outlier_count": diag_counters["absorbed_outlier_count"],
        "hard_split_count": diag_counters["hard_split_count"],
        "return_from_outlier_count": diag_counters["return_from_outlier_count"],
        "no_split_count": one_bin_song_count,
        "disc_artist": float(np.mean(disc_artist_vals)) if disc_artist_vals else 0.0,
        "disc_genre": float(np.mean(disc_genre_vals)) if disc_genre_vals else 0.0,
        "disc_head": float(np.mean(disc_head_vals)) if disc_head_vals else 0.0,
        "disc_general": float(np.mean(disc_general_vals)) if disc_general_vals else 0.0,
        "map_k": float(np.mean(map_vals)) if map_vals else 0.0,
        "mrr": float(np.mean(mrr_vals)) if mrr_vals else 0.0,
        "ndcg_k": float(np.mean(ndcg_vals)) if ndcg_vals else 0.0,
        "recall_k": float(np.mean(recall_vals)) if recall_vals else 0.0,
        "sim_checksum": sim_checksum,
    }
    _log.info(
        "[optimize] dist_thresh=%.3f  n=%d  mean_bins=%.1f  %s=%.4f",
        dist_thresh,
        n,
        float(bc_arr.mean()),
        objective,
        result,
    )
    return result, diag, layouts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def optimize_std_threshold(
    con,
    *,
    backbone: str,
    bin_mode: str,
    song_ids: frozenset[str] | set[str] | None = None,
    k: int = 10,
    objective: str = "disc_artist",
    search_range: tuple[float, float] = (0.1, 1.2),
    subsample_size: int = 200,
    tolerance: float = 0.05,
    max_evals: int = 15,
    seed: int = 42,
    method: str = "grid",
    grid: list[float] | None = None,
    grid_step: float = 0.05,
    flat_epsilon: float = 1e-8,
    rep_type: str = "median",
    agg_method: str = "median",
    metric: str = "cosine",
    csv_stem_suffix: str = "",
) -> OptimizationResult:
    """Find the optimal dist_threshold via golden section search.

    Evaluates the disc metric in-memory on a subsample of songs.  No
    calibration step is required — thresholds are direct cosine-space values.

    Parameters
    ----------
    con:
        Open DuckDB connection.
    backbone:
        Backbone name (e.g. ``"effnet"``).
    bin_mode:
        Binning mode (e.g. ``"temporal_global"``).
    song_ids:
        Optional set of song_ids to sample from.  If None, uses all songs.
    k:
        k for retrieval metrics.
    objective:
        Disc metric to maximize: ``disc_artist``, ``disc_album``,
        ``disc_genre``, or ``disc_general``.
    search_range:
        ``(low, high)`` bounds for dist_thresh search (cosine distance in
        [0, 2]; typical useful range 0.1–1.2).
    subsample_size:
        Number of songs to evaluate on (random sample).
    tolerance:
        Stop when search interval width < tolerance.
    max_evals:
        Hard cap on function evaluations.
    seed:
        RNG seed for reproducible subsampling.

    Returns
    -------
    OptimizationResult
        Best threshold/score bundle for this optimizer run.
    """
    if rep_type not in ("mean", "median", "medoid", "max", "min"):
        raise ValueError(f"Unsupported optimizer rep_type: {rep_type}")
    if agg_method == "medoid":
        raise ValueError("agg_method=medoid is not implemented; use agg_method=median with rep_type=medoid.")
    if agg_method not in _AGG_METHODS:
        raise ValueError(f"optimizer agg_method={agg_method!r} is not enabled in pooling.agg_methods={_AGG_METHODS}")
    if metric not in _SIM_METRICS:
        raise ValueError(f"optimizer metric={metric!r} is not enabled in similarity.metrics={_SIM_METRICS}")

    _log.info(
        "[optimize] backbone=%s  bin_mode=%s  objective=%s  method=%s  range=[%.2f, %.2f]  n=%d",
        backbone,
        bin_mode,
        objective,
        method,
        search_range[0],
        search_range[1],
        subsample_size,
    )
    _log.info(
        "[optimize] strategy rep_type=%s agg_method=%s metric=%s",
        rep_type,
        agg_method,
        metric,
    )
    if bin_mode == "temporal_global":
        _log.info("[optimize] temporal_global threshold is unit-vector L2 distance (NOT std multiplier)")

    # --- Build subsample -------------------------------------------------
    all_songs = _db.load_all_songs(con)
    if song_ids is not None:
        song_ids_str = {str(s) for s in song_ids}
        all_songs = [s for s in all_songs if str(s["song_id"]) in song_ids_str]

    rng = random.Random(seed)
    sample = rng.sample(all_songs, min(subsample_size, len(all_songs)))

    _log.info("[optimize] Loading patches for %d songs ...", len(sample))
    song_data: list[_SongEntry] = []
    skipped = 0
    for s in sample:
        sid = str(s["song_id"])
        sidecar = _patches_path(sid, backbone)
        if not sidecar.exists():
            skipped += 1
            continue
        try:
            raw_f32 = np.load(str(sidecar)).astype(np.float32)
        except Exception as exc:
            _log.info("[optimize] Skipping %s: %s", sidecar, exc)
            skipped += 1
            continue
        if len(raw_f32) < 2:
            skipped += 1
            continue
        song_data.append(
            (
                sid,
                s.get("artist") or "unknown",
                s.get("album"),
                s.get("genre"),
                raw_f32,
            )
        )

    if skipped:
        _log.info("[optimize] Skipped %d songs (no sidecar or too short)", skipped)

    n_valid = len(song_data)
    _log.info("[optimize] %d songs ready for evaluation", n_valid)

    # --- Optional head-score component (PTC/median) --------------------------
    head_scores_by_sid: dict[str, np.ndarray] | None = None
    head_names: list[str] | None = None
    if song_data:
        sample_sids = [sid for sid, *_ in song_data]
        hs, hn = _db.load_song_head_scores(backbone, sample_sids, strategy="median", pathway="ptc")
        if hs is not None and hn:
            head_scores_by_sid = {sid: hs[i] for i, sid in enumerate(sample_sids)}
            head_names = hn
            _log.info("[optimize] head component available in optimizer (%d heads)", len(hn))
        else:
            _log.info("[optimize] head component unavailable in optimizer")

    if n_valid < 10:
        mid = (search_range[0] + search_range[1]) / 2.0
        _log.warning(
            "[optimize] Only %d songs available (< 10) — returning midpoint %.2f",
            n_valid,
            mid,
        )
        return OptimizationResult(
            threshold=_canonical_threshold(mid),
            score=0.0,
        )

    # --- Evaluate thresholds --------------------------------------------
    thresholds = sorted({_canonical_threshold(t) for t in (grid or [])})
    if not thresholds:
        if method == "gss":
            # Keep legacy path available behind explicit opt-in.
            def _f(thresh: float) -> float:
                score, _diag, _layouts = _eval_threshold(
                    thresh,
                    backbone=backbone,
                    bin_mode=bin_mode,
                    song_data=song_data,
                    objective=objective,
                    k=k,
                    rep_type=rep_type,
                    agg_method=agg_method,
                    metric=metric,
                    head_scores_by_sid=head_scores_by_sid,
                    head_names=head_names,
                )
                return score

            a, b = search_range
            optimal_x, optimal_f, n_evals = _golden_section_max(_f, a, b, tol=tolerance, max_evals=max_evals)
            cx = _canonical_threshold(optimal_x)
            if bin_mode == "temporal_global":
                cos_equiv, angle_deg = _temporal_global_equivalents(cx)
                _log.info(
                    "[optimize] GSS result t=%s cos≈%.4f angle≈%.2f° score=%.6f evals=%d",
                    _threshold_key(cx),
                    cos_equiv,
                    angle_deg,
                    optimal_f,
                    n_evals,
                )
            return OptimizationResult(
                threshold=cx,
                score=float(optimal_f),
            )
        thresholds = _build_grid(search_range, step=grid_step)

    _log.info("[optimize] grid thresholds: %s", [f"{t:.3f}" for t in thresholds])
    prev_layouts: dict[str, tuple[tuple[int, ...], ...]] | None = None
    prev_checksum: str | None = None
    prev_score: float | None = None
    rows: list[tuple[float, float, dict, int]] = []
    for t in thresholds:
        score, diag, layouts = _eval_threshold(
            t,
            backbone=backbone,
            bin_mode=bin_mode,
            song_data=song_data,
            objective=objective,
            k=k,
            rep_type=rep_type,
            agg_method=agg_method,
            metric=metric,
            head_scores_by_sid=head_scores_by_sid,
            head_names=head_names,
        )
        changed = 0
        if prev_layouts:
            for sid, cur in layouts.items():
                prev = prev_layouts.get(sid)
                if prev is not None and prev != cur:
                    changed += 1
        changed_frac = float(changed / len(layouts)) if layouts else 0.0
        checksum = str(diag.get("sim_checksum", ""))
        if prev_checksum is not None and checksum == prev_checksum and changed > 0:
            _log.warning(
                "[optimize] layout changed but similarity matrix checksum unchanged at t=%s",
                _threshold_key(t),
            )
        if (
            prev_checksum is not None
            and checksum != prev_checksum
            and prev_score is not None
            and abs(score - prev_score) <= flat_epsilon
        ):
            _log.warning(
                "[optimize] similarity matrix changed but objective unchanged at t=%s (objective may be insensitive)",
                _threshold_key(t),
            )
        prev_layouts = layouts
        prev_checksum = checksum
        prev_score = score
        rows.append((t, score, diag, changed))

        if bin_mode == "temporal_global":
            cos_equiv, angle_deg = _temporal_global_equivalents(t)
            _log.info(
                "[optimize] t=%s cos≈%.4f angle≈%.2f° score=%.6f bins(mean=%.2f med=%.2f p95=%.2f one-bin=%.1f%% changed=%d)",
                _threshold_key(t),
                cos_equiv,
                angle_deg,
                score,
                diag["mean_bins_per_song"],
                diag["median_bins_per_song"],
                diag["p95_bins_per_song"],
                100.0 * diag["one_bin_song_frac"],
                changed,
            )
        else:
            _log.info(
                "[optimize] t=%s score=%.6f bins(mean=%.2f med=%.2f p95=%.2f one-bin=%.1f%% changed=%d)",
                _threshold_key(t),
                score,
                diag["mean_bins_per_song"],
                diag["median_bins_per_song"],
                diag["p95_bins_per_song"],
                100.0 * diag["one_bin_song_frac"],
                changed,
            )

    scores = [r[1] for r in rows]

    out_dir = _OUTPUT_ROOT / "optimizer"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"threshold_curve_{backbone}_{bin_mode}{csv_stem_suffix}.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "backbone",
                "bin_mode",
                "threshold",
                "threshold_key",
                "cosine_equiv",
                "angle_deg",
                "objective_total",
                "songs_evaluated",
                "total_bins",
                "mean_bins_per_song",
                "median_bins_per_song",
                "p95_bins_per_song",
                "one_bin_song_frac",
                "single_segment_bins",
                "layout_changed_count_vs_prev",
                "layout_changed_frac_vs_prev",
                "distance_boundary_count",
                "absorbed_outlier_count",
                "hard_split_count",
                "return_from_outlier_count",
                "disc_artist",
                "disc_genre",
                "disc_head",
                "disc_general",
                "map_k",
                "mrr",
                "ndcg_k",
                "recall_k",
                "sim_checksum",
            ],
        )
        writer.writeheader()
        for t, score, diag, _changed in rows:
            # Recompute changed frac from already-tracked count for CSV visibility.
            # Uses the current threshold's evaluated song count as denominator.
            changed_frac = float(_changed / diag["songs_evaluated"]) if diag["songs_evaluated"] else 0.0
            cos_equiv = angle_deg = None
            if bin_mode == "temporal_global":
                cos_equiv, angle_deg = _temporal_global_equivalents(t)
            writer.writerow(
                {
                    "backbone": backbone,
                    "bin_mode": bin_mode,
                    "threshold": t,
                    "threshold_key": _threshold_key(t),
                    "cosine_equiv": cos_equiv,
                    "angle_deg": angle_deg,
                    "objective_total": score,
                    "songs_evaluated": diag["songs_evaluated"],
                    "total_bins": diag["total_bins"],
                    "mean_bins_per_song": diag["mean_bins_per_song"],
                    "median_bins_per_song": diag["median_bins_per_song"],
                    "p95_bins_per_song": diag["p95_bins_per_song"],
                    "one_bin_song_frac": diag["one_bin_song_frac"],
                    "single_segment_bins": diag["single_segment_bins"],
                    "layout_changed_count_vs_prev": _changed,
                    "layout_changed_frac_vs_prev": changed_frac,
                    "distance_boundary_count": diag["distance_boundary_count"],
                    "absorbed_outlier_count": diag["absorbed_outlier_count"],
                    "hard_split_count": diag["hard_split_count"],
                    "return_from_outlier_count": diag["return_from_outlier_count"],
                    "disc_artist": diag["disc_artist"],
                    "disc_genre": diag["disc_genre"],
                    "disc_head": diag["disc_head"],
                    "disc_general": diag["disc_general"],
                    "map_k": diag["map_k"],
                    "mrr": diag["mrr"],
                    "ndcg_k": diag["ndcg_k"],
                    "recall_k": diag["recall_k"],
                    "sim_checksum": diag["sim_checksum"],
                }
            )
    _log.info("[optimize] threshold curve table written: %s", out_csv)

    score_range = max(scores) - min(scores) if scores else 0.0
    bins_mean = [r[2]["mean_bins_per_song"] for r in rows]
    bin_range = (max(bins_mean) - min(bins_mean)) if bins_mean else 0.0

    if score_range < flat_epsilon:
        _log.warning("[optimize] status=inconclusive_flat_objective score_range=%.3e", score_range)
        if abs(bin_range) < 1e-12:
            _log.warning("[optimize] segmentation unchanged over thresholds (mean-bin range=%.3e)", bin_range)
        return OptimizationResult(
            threshold=_canonical_threshold((search_range[0] + search_range[1]) / 2.0),
            score=float(max(scores)) if scores else 0.0,
        )

    best_t, best_score, _best_diag, _changed = max(rows, key=lambda x: x[1])
    _log.info(
        "[optimize] Done — optimal dist_thresh=%s %s=%.6f  (evaluated=%d)",
        _threshold_key(best_t),
        objective,
        best_score,
        len(rows),
    )
    return OptimizationResult(
        threshold=_canonical_threshold(best_t),
        score=float(best_score),
    )
