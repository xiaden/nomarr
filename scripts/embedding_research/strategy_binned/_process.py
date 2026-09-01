"""Song processing helpers for analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass as _dataclass
from typing import TYPE_CHECKING
from typing import NamedTuple as _NamedTuple

import numpy as _np
import scipy.stats as _scipy_stats

from scripts.embedding_research import db as _db
from scripts.embedding_research.scoring_harness import (
    PRIMARY_COLLISION_POLICY as _PRIMARY_COLLISION_POLICY,
)
from scripts.embedding_research.scoring_harness import (
    PRIMARY_TIE_POLICY as _PRIMARY_TIE_POLICY,
)
from scripts.embedding_research.scoring_harness import (
    SegmentScoreInput as _SegmentScoreInput,
)
from scripts.embedding_research.scoring_harness import (
    SegmentScoreTrace as _SegmentScoreTrace,
)
from scripts.embedding_research.scoring_harness import (
    score_max_per_candidate_segment as _score_max_per_candidate_segment,
)
from scripts.embedding_research.scoring_harness import (
    variant_name as _variant_name,
)
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


from ._constants import (
    AGG_METHODS,
)
from ._constants import (
    PRIMARY_SCORE_VARIANT as _PRIMARY_SCORE_VARIANT,
)
from ._constants import (
    validate_score_variant as _validate_score_variant,
)
from ._weighted import (
    bidirectional_weighted as _bidirectional_weighted,
)
from ._weighted import (
    normalized_mean_pair_weighted as _normalized_mean_pair_weighted,
)
from ._weighted import (
    target_weighted as _target_weighted,
)

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
    weights_a: list[_np.ndarray],
    weights_b: list[_np.ndarray],
    metric: str,
    *,
    progress=None,
) -> dict[str, _np.ndarray]:
    """Compute pairwise weighted directional similarity matrices for one (rep_a, rep_b) pair.

    Every **ordered** ``(i, j)`` song pair is evaluated independently, including
    ``i == j`` (diagonal, from the same formula — never unconditionally set to
    1.0) and ``i > j``.  No similarity matrix is mirrored: the forward matrix is
    ``S_ij`` (source bins of song ``i`` under ``rep_a`` -> target bins of song
    ``j`` under ``rep_b``) and the reverse matrix for the bidirectional reduction
    is the separately computed ``S_ji`` (source bins of ``j`` under ``rep_a`` ->
    target bins of ``i`` under ``rep_b``), which is *not* assumed symmetric with
    ``S_ij`` because ``rep_a`` and ``rep_b`` are distinct representations.

    Parameters
    ----------
    norm_a, norm_b:
        Per-song bin vectors as UnitTensor, each ``[n_bins, D] float32``.  Rows
        are guaranteed unit-normalised by the UnitTensor setter (old cache files
        are re-normalised by the UnitTensor setter on load via
        ``cache.binned_ptc.load_norm_pair`` / ``cache.binned_ctp.load_all_reps``).
    weights_a, weights_b:
        Per-song temporal patch-count weights, one entry per song; each entry is
        the ``[n_bins]`` weight array of that song (``weights_a[i]`` weights
        ``norm_a[i]`` source bins, ``weights_b[j]`` weights ``norm_b[j]`` target
        bins).  Lengths must match the corresponding bin dimensions.
    metric:
        Only ``"cosine"`` is supported (l2 was removed).
    progress:
        Optional tqdm-compatible progress object; updated once per song row.

    Returns
    -------
    dict mapping each configured aggregate name to an ``[n, n] float32`` matrix.
    ``target_weighted`` and ``normalized_mean_pair_weighted`` are directional;
    ``bidirectional_weighted`` is symmetric by construction (it averages both
    supplied directions).  Legacy generic reductions and ``agg_method=medoid``
    are rejected here and at the validation boundary in ``_constants.py``.
    """
    if metric != "cosine":
        raise ValueError(f"Only metric='cosine' is supported, got {metric!r}")
    n = len(norm_a)
    agg_mats: dict[str, _np.ndarray] = {agg: _np.zeros((n, n), dtype=_np.float32) for agg in AGG_METHODS}

    # Unpack to ndarray once — UnitTensor setter already guarantees unit rows.
    data_a = [v.data for v in norm_a]
    data_b = [v.data for v in norm_b]
    w_a = [_np.asarray(w, dtype=_np.float64) for w in weights_a]
    w_b = [_np.asarray(w, dtype=_np.float64) for w in weights_b]

    for i in range(n):
        va = data_a[i]
        wa = w_a[i]
        for j in range(n):
            vb = data_b[j]
            # Forward similarity: source bins of i (rep_a) -> target bins of j (rep_b).
            sim = (va @ vb.T).astype(_np.float32)
            wb = w_b[j]
            for agg in AGG_METHODS:
                if agg == "target_weighted":
                    val = _target_weighted(sim, wb)
                elif agg == "normalized_mean_pair_weighted":
                    val = _normalized_mean_pair_weighted(sim, wa, wb)
                elif agg == "bidirectional_weighted":
                    # Reverse S_ji: source bins of j (rep_a) -> target bins of i (rep_b).
                    # Never derived by transposing the forward matrix.
                    rev = (data_a[j] @ data_b[i].T).astype(_np.float32)
                    val = _bidirectional_weighted(sim, rev, wb, wa)
                else:
                    raise ValueError(
                        f"Unsupported agg_method: {agg}. Legacy generic reductions and agg_method=medoid are rejected."
                    )
                agg_mats[agg][i, j] = val
        if progress is not None:
            progress.update(1)

    return agg_mats


@_dataclass(frozen=True)
class ScoreVariantResult:
    """Scalar retrieval matrix plus bounded per-pair provenance traces.

    ``matrix[i, j]`` is the ``score_variant`` score for the **ordered** pair with
    song ``i`` as source and song ``j`` as candidate (rows = source).  ``traces[i][j]``
    is the matching ``SegmentScoreTrace``.  Reverse pairs (``[j, i]``) are computed
    separately from the actual reverse arrays — never copied from a transpose.
    The trace records are bounded (one per pair), so the pair-level provenance can
    be summarised without ever persisting the raw ``n*n`` matrix into scalar rows.
    """

    score_variant: str
    variant: str
    tie_policy: str
    collision_policy: str
    matrix: _np.ndarray
    traces: tuple[tuple[_SegmentScoreTrace, ...], ...]

    @property
    def n(self) -> int:
        return int(self.matrix.shape[0])


def compute_score_variant_mats(
    norm_a: list[_UnitTensor],
    norm_b: list[_UnitTensor],
    weights_a: list[_np.ndarray],
    weights_b: list[_np.ndarray],
    metric: str,
    *,
    score_variant: str = _PRIMARY_SCORE_VARIANT,
    tie_policy: str = _PRIMARY_TIE_POLICY,
    collision_policy: str = _PRIMARY_COLLISION_POLICY,
    progress=None,
) -> ScoreVariantResult:
    """Compute the primary ``max_per_candidate_segment`` score variant for one
    ``(rep_a, rep_b)`` pair, returning both the scalar ``[n, n]`` matrix and the
    bounded per-pair ``SegmentScoreTrace`` records.

    Every ordered ``(i, j)`` pair (including ``i == j`` and ``i > j``) is scored
    independently from the actual ``rep_a`` source bins of song ``i`` against the
    ``rep_b`` candidate bins of song ``j``.  Reverse pairs are computed separately
    from their own arrays — never by transposing or copying the forward matrix.

    ``score_variant`` is validated against ``validate_score_variant`` so an
    unlabelled generic mean/median/max/min/medoid aggregate cannot re-enter as a
    primary scoring method.  The legacy weighted reductions are *not* implemented
    here (they are opt-in hypotheses computed by ``compute_agg_mats``); requesting
    one raises ``ValueError``.
    """
    if metric != "cosine":
        raise ValueError(f"Only metric='cosine' is supported, got {metric!r}")
    _validate_score_variant(score_variant)
    if score_variant != _PRIMARY_SCORE_VARIANT:
        raise ValueError(
            f"compute_score_variant_mats implements only the primary "
            f"{_PRIMARY_SCORE_VARIANT!r} variant, got {score_variant!r}; the legacy "
            "weighted hypotheses are computed by compute_agg_mats."
        )
    n = len(norm_a)
    data_a = [v.data for v in norm_a]
    data_b = [v.data for v in norm_b]
    w_a = [_np.asarray(w, dtype=_np.float64) for w in weights_a]
    w_b = [_np.asarray(w, dtype=_np.float64) for w in weights_b]

    matrix = _np.zeros((n, n), dtype=_np.float32)
    traces: list[list[_SegmentScoreTrace]] = [[None for _ in range(n)] for _ in range(n)]  # type: ignore[misc]
    for i in range(n):
        for j in range(n):
            trace = _score_max_per_candidate_segment(
                _SegmentScoreInput(data_a[i], data_b[j], w_a[i], w_b[j]),
                tie_policy=tie_policy,
                collision_policy=collision_policy,
            )
            matrix[i, j] = float(trace.score)
            traces[i][j] = trace
        if progress is not None:
            progress.update(1)

    return ScoreVariantResult(
        score_variant=score_variant,
        variant=_variant_name(tie_policy, collision_policy),
        tie_policy=tie_policy,
        collision_policy=collision_policy,
        matrix=matrix,
        traces=tuple(tuple(row) for row in traces),
    )


def score_variant_trace_summary(result: ScoreVariantResult) -> dict[str, float]:
    """Bounded, finite-only scalar summary of the per-pair traces.

    Returns only finite scalar aggregates (pair counts, summed/mean numerators and
    denominators, collision/winner/retained/dropped counts) — never the raw
    ``n*n`` matrix or the per-pair contribution arrays.  This is the persisted
    trace-provenance surface at the scalar-metrics DB/report boundary; the full
    strategy key (whose ``agg_method`` carries the score-variant identity) is the
    trace reference.
    """
    flat = [tr for row in result.traces for tr in row]
    n_pairs = len(flat)
    numerator = sum(float(tr.numerator) for tr in flat)
    denominator = sum(float(tr.denominator) for tr in flat)
    collisions = sum(len(tr.collisions) for tr in flat)
    winners = sum(sum(count for _, count in tr.winner_counts) for tr in flat)
    retained = sum(1 for tr in flat for c in tr.contributions if c.retained)
    dropped = sum(1 for tr in flat for c in tr.contributions if not c.retained)
    finite = all(tr.finite for tr in flat)
    return {
        "trace_n_pairs": float(n_pairs),
        "trace_numerator_sum": float(numerator),
        "trace_denominator_sum": float(denominator),
        "trace_numerator_mean": float(numerator / n_pairs) if n_pairs else 0.0,
        "trace_denominator_mean": float(denominator / n_pairs) if n_pairs else 0.0,
        "trace_collision_count": float(collisions),
        "trace_winner_count": float(winners),
        "trace_retained_contributions": float(retained),
        "trace_dropped_contributions": float(dropped),
        "trace_finite": 1.0 if finite else 0.0,
    }


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


def compute_score_variant_retrieval_rows(
    result: ScoreVariantResult,
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
    head_scores: list[list[float]] | None = None,
    head_names: list[str] | None = None,
) -> tuple[list[_BinnedRetrievalRow], list[tuple], dict[str, float]]:
    """Derive retrieval rows from a primary score-variant result.

    Returns ``(rows, per_head_rows, trace_summary)`` where ``rows`` carry
    ``agg_method=result.score_variant`` (the explicit score-variant identity in
    the retrieval-row DTO) and ``trace_summary`` is the bounded, finite-only
    per-pair provenance summary (``score_variant_trace_summary``).  Reverse
    directions were already computed separately by ``compute_score_variant_mats``
    — never from a transpose.
    """
    metrics = _compute_retrieval_metrics(
        result.matrix,
        artists,
        k=k,
        albums=albums,
        genres=genres,
        head_scores=head_scores,
        head_names=head_names,
    )
    metrics["n_songs"] = n_songs
    rows: list[_BinnedRetrievalRow] = [
        _BinnedRetrievalRow.from_metrics(
            backbone,
            bin_mode,
            std_thresh,
            rep_a,
            rep_b,
            metric,
            result.score_variant,
            k,
            metrics,
        )
    ]
    per_head_rows: list[tuple] = [
        (backbone, bin_mode, std_thresh, rep_a, rep_b, metric, result.score_variant, k, h_name, corr)
        for h_name, corr in metrics.get("per_head_corr", {}).items()
    ]
    return rows, per_head_rows, score_variant_trace_summary(result)


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
    # reps_a / reps_b are unused (computation operates on norms only).
    # Legacy wrapper has no per-bin weights; fall back to uniform per-bin weights.
    weights = [_np.ones(int(c), dtype=_np.float32) for c in bin_counts]
    agg_mats = compute_agg_mats(norm_a, norm_b, weights, weights, metric, progress=progress)
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
