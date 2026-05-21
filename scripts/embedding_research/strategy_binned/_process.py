"""Song processing helpers for analysis pipeline."""

from __future__ import annotations

import numpy as _np

from .. import db as _db
from ..similarity import compute_retrieval_metrics as _compute_retrieval_metrics
from ._constants import AGG_METHODS


def _compute_song_stats(
    sid: str,
    bins_list: list[dict],
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    con,
) -> None:
    n_bins = len(bins_list)
    weights = [b["weight"] for b in bins_list]
    n_patches = sum(weights)
    n_outliers = sum(b.get("outlier_count", 0) for b in bins_list)

    bin_div_std = 0.0
    if n_bins >= 2:
        mean_vecs = _np.stack([b["vec_mean"] for b in bins_list])
        norms = mean_vecs / (_np.linalg.norm(mean_vecs, axis=1, keepdims=True) + 1e-9)
        cos_mat = norms @ norms.T
        pairs = cos_mat[_np.triu_indices(n_bins, k=1)]
        bin_div_std = float(pairs.std())

    _db.upsert_binned_song_stats(
        con,
        sid,
        backbone,
        bin_mode,
        std_thresh,
        {
            "n_bins": n_bins,
            "n_patches": n_patches,
            "n_outliers": n_outliers,
            "min_bin_size": min(weights),
            "max_bin_size": max(weights),
            "mean_bin_size": float(_np.mean(weights)),
            "bin_div_std": bin_div_std,
        },
    )


def compute_agg_mats(
    norm_a: list[_np.ndarray],
    norm_b: list[_np.ndarray],
    bin_counts: _np.ndarray,
    metric: str,
    *,
    progress=None,
) -> dict[str, _np.ndarray]:
    """Compute pairwise aggregated similarity matrices for one (rep_a, rep_b, metric) pair.

    Parameters
    ----------
    norm_a, norm_b:
        Per-song L2-normalised bin vectors, each ``[n_bins, D] float32``.
    bin_counts:
        Number of bins per song ``[n_songs] float32``.
    metric:
        One of ``"cosine"`` or ``"l2"``.
    progress:
        Optional tqdm-compatible progress object; updated once per song row.

    Returns
    -------
    dict mapping each agg method name to an ``[n, n] float32`` matrix.
    """
    n = len(norm_a)
    agg_mats: dict[str, _np.ndarray] = {agg: _np.zeros((n, n), dtype=_np.float32) for agg in AGG_METHODS}

    if metric == "cosine":
        sums_a = _np.stack([na.sum(axis=0) for na in norm_a])
        sums_b = _np.stack([nb.sum(axis=0) for nb in norm_b])
        mean_mat = (sums_a @ sums_b.T) / _np.outer(bin_counts, bin_counts)
        _np.fill_diagonal(mean_mat, 1.0)
        agg_mats["mean"] = mean_mat.astype(_np.float32)

    loop_aggs = [agg for agg in AGG_METHODS if not (metric == "cosine" and agg == "mean")]
    if loop_aggs:
        sq_list_a = [(va * va).sum(axis=1).astype(_np.float32) for va in norm_a] if metric == "l2" else None
        sq_list_b = [(vb * vb).sum(axis=1).astype(_np.float32) for vb in norm_b] if metric == "l2" else None

        for i in range(n):
            va = norm_a[i]
            js = list(range(i + 1, n))
            if js:
                vb_blocks = [norm_b[j] for j in js]
                sizes = [block.shape[0] for block in vb_blocks]
                vb_cat = _np.concatenate(vb_blocks, axis=0)
                dot_cat = (va @ vb_cat.T).astype(_np.float32)
                if metric == "l2":
                    if sq_list_a is None or sq_list_b is None:
                        raise RuntimeError("L2 cache lists were not initialised")
                    sq_a = sq_list_a[i][:, None]
                    sq_b_cat = _np.concatenate([sq_list_b[j] for j in js], axis=0)[None, :]
                    sq_dist = _np.maximum(sq_a + sq_b_cat - 2.0 * dot_cat, 0.0)
                    sim_cat = (1.0 / (1.0 + _np.sqrt(sq_dist))).astype(_np.float32)
                else:
                    sim_cat = dot_cat

                start = 0
                for j, width in zip(js, sizes, strict=False):
                    end = start + width
                    sim = sim_cat[:, start:end]
                    start = end
                    for agg in loop_aggs:
                        if agg == "mean":
                            val = float(sim.mean())
                        elif agg == "median":
                            val = float(_np.median(sim))
                        elif agg == "max":
                            val = float(sim.max())
                        else:
                            val = float(sim.min())
                        agg_mats[agg][i, j] = val
                        agg_mats[agg][j, i] = val
            if progress is not None:
                progress.update(1)

        for agg in loop_aggs:
            _np.fill_diagonal(agg_mats[agg], 1.0)

    return agg_mats


def compute_retrieval_rows(
    agg_mats: dict[str, _np.ndarray],
    artists: list[str],
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    rep_a: str,
    rep_b: str,
    metric: str,
    k: int,
    *,
    albums: list[str] | None = None,
    genres: list[str] | None = None,
    head_scores: _np.ndarray | None = None,
    head_names: list[str] | None = None,
) -> tuple[list[tuple], list[tuple]]:
    """Derive retrieval metric rows from pre-computed aggregated similarity matrices.

    Fast — O(n log n) argsort per matrix.  Separated from ``compute_agg_mats``
    so that cached matrices can skip the expensive O(n²) computation entirely.
    """
    rows: list[tuple] = []
    per_head_rows: list[tuple] = []
    for agg in AGG_METHODS:
        metrics = _compute_retrieval_metrics(
            agg_mats[agg],
            artists,
            k=k,
            albums=albums,
            genres=genres,
            head_scores=head_scores,
            head_names=head_names,
        )
        rows.append(
            (
                backbone,
                bin_mode,
                std_thresh,
                rep_a,
                rep_b,
                metric,
                agg,
                k,
                metrics.get("disc_score"),
                metrics.get(f"map_{k}"),
                metrics.get("mrr"),
                metrics.get(f"ndcg_{k}"),
                metrics.get(f"recall_{k}"),
                metrics.get(f"recall_{k}_album"),
                metrics.get(f"recall_{k}_genre"),
                metrics.get("mean_within"),
                metrics.get("mean_cross"),
                metrics.get("disc_artist"),
                metrics.get("disc_album"),
                metrics.get("disc_genre"),
                metrics.get("disc_head"),
            )
        )
        for h_name, corr in metrics.get("per_head_corr", {}).items():
            per_head_rows.append(
                (backbone, bin_mode, std_thresh, rep_a, rep_b, metric, agg, k, h_name, corr)
            )
    return rows, per_head_rows


def _process_group(
    reps_a: list[_np.ndarray],
    reps_b: list[_np.ndarray],
    norm_a: list[_np.ndarray],
    norm_b: list[_np.ndarray],
    bin_counts: _np.ndarray,
    artists: list[str],
    rep_a: str,
    rep_b: str,
    metric: str,
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    k: int,
    progress,
    albums: list[str] | None = None,
    genres: list[str] | None = None,
    head_scores: _np.ndarray | None = None,
    head_names: list[str] | None = None,
) -> tuple[list[tuple], list[tuple]]:
    """Legacy wrapper used by ``analyze_ctp``.  New code should call
    ``compute_agg_mats`` + ``compute_retrieval_rows`` directly."""
    # reps_a / reps_b are unused (computation operates on norms only)
    agg_mats = compute_agg_mats(norm_a, norm_b, bin_counts, metric, progress=progress)
    return compute_retrieval_rows(
        agg_mats, artists, backbone, bin_mode, std_thresh,
        rep_a, rep_b, metric, k,
        albums=albums, genres=genres,
        head_scores=head_scores, head_names=head_names,
    )
