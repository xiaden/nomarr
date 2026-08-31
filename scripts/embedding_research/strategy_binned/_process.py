"""Song processing helpers for analysis pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import NamedTuple as _NamedTuple

import numpy as _np
import scipy.stats as _scipy_stats

from scripts.embedding_research import db as _db
from scripts.embedding_research.similarity import compute_retrieval_metrics as _compute_retrieval_metrics

try:
    from scripts.embedding_research.db._types import BinnedRetrievalRow as _BinnedRetrievalRow
except ImportError:

    class _BinnedRetrievalRow(_NamedTuple):
        backbone: str
        bin_mode: str
        std_thresh: float
        rep_a: str
        rep_b: str
        sim_metric: str
        agg_method: str
        k: int
        disc_score: float | None
        map_k: float | None
        mrr: float | None
        ndcg_k: float | None
        recall_k: float | None
        recall_k_genre: float | None
        mean_within: float | None
        mean_cross: float | None
        disc_artist: float | None
        disc_genre: float | None
        disc_head: float | None
        disc_general: float | None
        precision_k_genre: float | None
        precision_k_head_mean: float | None
        flat_binned_spearman: float | None
        flat_binned_beneficial_reorder_rate: float | None
        n_songs: int | None = None
        map_k_genre: float | None = None
        mrr_genre: float | None = None
        ndcg_k_genre: float | None = None
        map_k_head: float | None = None
        mrr_head: float | None = None
        ndcg_k_head: float | None = None
        recall_k_head: float | None = None

        def as_tuple(self) -> tuple:
            return tuple(self)

        @classmethod
        def from_metrics(
            cls,
            backbone: str,
            bin_mode: str,
            std_thresh: float,
            rep_a: str,
            rep_b: str,
            sim_metric: str,
            agg_method: str,
            k: int,
            metrics: dict,
        ) -> _BinnedRetrievalRow:
            return cls(
                backbone=backbone,
                bin_mode=bin_mode,
                std_thresh=std_thresh,
                rep_a=rep_a,
                rep_b=rep_b,
                sim_metric=sim_metric,
                agg_method=agg_method,
                k=k,
                disc_score=metrics.get("disc_score"),
                map_k=metrics.get("map_k_artist"),
                mrr=metrics.get("mrr"),
                ndcg_k=metrics.get("ndcg_k_artist"),
                recall_k=metrics.get("recall_k_artist"),
                recall_k_genre=metrics.get("recall_k_genre"),
                mean_within=metrics.get("mean_within"),
                mean_cross=metrics.get("mean_cross"),
                disc_artist=metrics.get("disc_artist"),
                disc_genre=metrics.get("disc_genre"),
                disc_head=metrics.get("disc_head"),
                disc_general=metrics.get("disc_general"),
                precision_k_genre=metrics.get("precision_k_genre"),
                precision_k_head_mean=metrics.get("precision_k_head_mean"),
                flat_binned_spearman=metrics.get("flat_binned_spearman"),
                flat_binned_beneficial_reorder_rate=metrics.get("flat_binned_beneficial_reorder_rate"),
                n_songs=metrics.get("n_songs"),
                map_k_genre=metrics.get("map_k_genre"),
                mrr_genre=metrics.get("mrr_genre"),
                ndcg_k_genre=metrics.get("ndcg_k_genre"),
                map_k_head=metrics.get("map_k_head"),
                mrr_head=metrics.get("mrr_head"),
                ndcg_k_head=metrics.get("ndcg_k_head"),
                recall_k_head=metrics.get("recall_k_head"),
            )


from ._constants import AGG_METHODS

if TYPE_CHECKING:
    from scripts.embedding_research.vector_types import UnitTensor as _UnitTensor


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
        },
    )


def compute_agg_mats(
    norm_a: list[_UnitTensor],
    norm_b: list[_UnitTensor],
    bin_counts: _np.ndarray,
    metric: str,
    *,
    progress=None,
) -> dict[str, _np.ndarray]:
    """Compute pairwise aggregated similarity matrices for one (rep_a, rep_b, metric) pair.

    Parameters
    ----------
    norm_a, norm_b:
        Per-song bin vectors as UnitTensor, each ``[n_bins, D] float32``.  Rows
        are guaranteed unit-normalised by the UnitTensor setter (old cache files
        are re-normalised by the UnitTensor setter on load via
        ``cache.binned_ptc.load_norm_pair`` / ``cache.binned_ctp.load_all_reps``).
    bin_counts:
        Number of bins per song ``[n_songs] float32``.
    metric:
        Only ``"cosine"`` is supported (l2 was removed).
    progress:
        Optional tqdm-compatible progress object; updated once per song row.

    Returns
    -------
    dict mapping each agg method name to an ``[n, n] float32`` matrix.
    """
    n = len(norm_a)
    agg_mats: dict[str, _np.ndarray] = {agg: _np.zeros((n, n), dtype=_np.float32) for agg in AGG_METHODS}

    # Unpack to ndarray once — UnitTensor setter already guarantees unit rows.
    data_a = [v.data for v in norm_a]
    data_b = [v.data for v in norm_b]

    # Fast path: mean aggregation for cosine metric.
    sums_a = _np.stack([da.sum(axis=0) for da in data_a])
    sums_b = _np.stack([db.sum(axis=0) for db in data_b])
    mean_mat = (sums_a @ sums_b.T) / _np.outer(bin_counts, bin_counts)
    _np.fill_diagonal(mean_mat, 1.0)
    if "mean" in agg_mats:
        agg_mats["mean"] = mean_mat.astype(_np.float32)

    loop_aggs = [agg for agg in AGG_METHODS if agg != "mean"]
    if loop_aggs:
        for i in range(n):
            va = data_a[i]
            js = list(range(i + 1, n))
            if js:
                vb_blocks = [data_b[j] for j in js]
                sizes = [block.shape[0] for block in vb_blocks]
                vb_cat = _np.concatenate(vb_blocks, axis=0)
                sim_cat = (va @ vb_cat.T).astype(_np.float32)

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
                        elif agg == "medoid":
                            raise ValueError(
                                "agg_method=medoid is not implemented; use agg_method=median with rep_type=medoid."
                            )
                        elif agg == "max":
                            val = float(sim.max())
                        elif agg == "min":
                            val = float(sim.min())
                        else:
                            raise ValueError(f"Unsupported agg_method: {agg}")
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
    n_songs: int,
    *,
    albums: list[str] | None = None,
    genres: list[str] | None = None,
    flat_upper_tri: _np.ndarray | None = None,
    flat_sids: list[str] | None = None,
    current_sids: list[str] | None = None,
    head_scores: list[list[float]] | None = None,
    head_names: list[str] | None = None,
) -> tuple[list[_BinnedRetrievalRow], list[tuple]]:
    """Derive retrieval metric rows from pre-computed aggregated similarity matrices.

    Fast — O(n log n) argsort per matrix.  Separated from ``compute_agg_mats``
    so that cached matrices can skip the expensive O(n²) computation entirely.
    """
    rows: list[_BinnedRetrievalRow] = []
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
        if flat_upper_tri is not None and flat_sids is not None and current_sids is not None:
            flat_idx = {s: i for i, s in enumerate(flat_sids)}
            curr_idx = {s: i for i, s in enumerate(current_sids)}
            common = [s for s in current_sids if s in flat_idx]

            if len(common) >= 2:
                fi = [flat_idx[s] for s in common]
                ci = [curr_idx[s] for s in common]
                n_c = len(common)
                f_i, f_j = _np.triu_indices(n_c, k=1)

                flat_mat_size = len(flat_sids)
                flat_full = _np.zeros((flat_mat_size, flat_mat_size), dtype=flat_upper_tri.dtype)
                f_ti, f_tj = _np.triu_indices(flat_mat_size, k=1)
                flat_full[f_ti, f_tj] = flat_upper_tri
                flat_full = flat_full + flat_full.T
                flat_sub = flat_full[_np.ix_(fi, fi)]
                flat_aligned = flat_sub[f_i, f_j]

                binned_sub = agg_mats[agg][_np.ix_(ci, ci)]
                binned_aligned = binned_sub[f_i, f_j]

                spearman_stat = _scipy_stats.spearmanr(flat_aligned, binned_aligned).statistic
                metrics["flat_binned_spearman"] = float(spearman_stat)

                flat_ranks = _np.argsort(_np.argsort(-flat_aligned))
                binned_ranks = _np.argsort(_np.argsort(-binned_aligned))
                rank_delta = _np.abs(flat_ranks.astype(float) - binned_ranks.astype(float))
                n_pairs = len(flat_aligned)
                top_k = min(200, n_pairs)
                top_indices = _np.argsort(-rank_delta)[:top_k]

                if genres is not None and top_k > 0:
                    within_genre_improved = 0
                    for idx in top_indices:
                        pi, pj = f_i[idx], f_j[idx]
                        song_i = common[pi]
                        song_j = common[pj]
                        ci_song = curr_idx[song_i]
                        cj_song = curr_idx[song_j]
                        g_i = genres[ci_song] if ci_song < len(genres) else None
                        g_j = genres[cj_song] if cj_song < len(genres) else None
                        if g_i and g_j and g_i == g_j and binned_ranks[idx] < flat_ranks[idx]:
                            within_genre_improved += 1
                    metrics["flat_binned_beneficial_reorder_rate"] = within_genre_improved / top_k
                else:
                    metrics["flat_binned_beneficial_reorder_rate"] = None
            else:
                metrics["flat_binned_spearman"] = None
                metrics["flat_binned_beneficial_reorder_rate"] = None
        metrics["n_songs"] = n_songs
        rows.append(
            _BinnedRetrievalRow.from_metrics(backbone, bin_mode, std_thresh, rep_a, rep_b, metric, agg, k, metrics)
        )
        for h_name, corr in metrics.get("per_head_corr", {}).items():
            per_head_rows.append((backbone, bin_mode, std_thresh, rep_a, rep_b, metric, agg, k, h_name, corr))
    return rows, per_head_rows


def _process_group(
    norm_a: list[_UnitTensor],
    norm_b: list[_UnitTensor],
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
    n_songs: int = 0,
) -> tuple[list[_BinnedRetrievalRow], list[tuple]]:
    """Compatibility wrapper retained for legacy callers; the live shared
    analysis path (``common.analyze.analyze``) composes ``compute_agg_mats`` +
    ``compute_retrieval_rows`` directly."""
    # reps_a / reps_b are unused (computation operates on norms only)
    agg_mats = compute_agg_mats(norm_a, norm_b, bin_counts, metric, progress=progress)
    return compute_retrieval_rows(
        agg_mats,
        artists,
        backbone,
        bin_mode,
        std_thresh,
        rep_a,
        rep_b,
        metric,
        k,
        n_songs,
        albums=albums,
        genres=genres,
        head_scores=head_scores,
        head_names=head_names,
    )
