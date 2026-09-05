"""Similarity metrics and retrieval quality measures (EXACT CPU only).

This module computes exact CPU similarity/metrics only: cosine similarity over
L2-normalised vectors and the retrieval/discrimination metrics built on it.  The
former ANN surface (``ANNIndex``, ``ann_recall_sweep``, the optional FAISS backend
and its lazy import) was deleted under Plan D P1-S6; no ANN index, approximate
nearest-neighbour backend, or FAISS dependency exists here or elsewhere in the
retained research tree.

Metrics:
  cosine  - cosine similarity (direction only; L2-normalised dot product)

Retrieval metrics:
  MAP@k, MRR, NDCG@k, Recall@k computed over artist, genre, and head labels.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

    from .vector_types import RawTensor, UnitTensor

_log = logging.getLogger(__name__)

try:
    from sklearn.metrics import ndcg_score as _sklearn_ndcg

    _SKLEARN = True
except ImportError:
    _SKLEARN = False


# Hyperparameter: disc_head window-based scoring
DISC_HEAD_WINDOW: float = 0.1  # half-width of the in-set score neighborhood
DISC_HEAD_GAP: float = 0.1  # minimum score gap before a song enters the out-set


# -- L2-normalisation -------------------------------------------------------


def l2_normalise(vecs: RawTensor) -> UnitTensor:
    """Return unit-norm vectors [n, d]."""
    return vecs.normalize()


# -- Pairwise similarity / distance matrices --------------------------------


def cosine_matrix(vecs: RawTensor) -> np.ndarray:
    """[n, n] cosine similarity matrix."""
    normed = vecs.normalize().data
    return np.asarray((normed @ normed.T).astype(np.float32))


# dot omitted: on L2-normalised vectors it equals cosine; no additional signal.
# l2 removed: prior testing determined cosine is superior across the board.
METRICS: dict[str, Callable[[RawTensor], np.ndarray]] = {
    "cosine": cosine_matrix,
}


# -- Retrieval helper -------------------------------------------------------


def _rankings_from_sim(sim_matrix: np.ndarray) -> np.ndarray:
    """[n, n-1] sorted descending indices, self excluded."""
    n = sim_matrix.shape[0]
    out = np.empty((n, n - 1), dtype=np.int32)
    for i in range(n):
        row = sim_matrix[i].copy()
        row[i] = -np.inf  # self sinks to last position after argsort
        sorted_idx = np.argsort(-row)  # shape (n,); self is always at index n-1
        out[i] = sorted_idx[: n - 1]  # drop the last element (self)
    return out


def compute_retrieval_metrics(
    sim_matrix: np.ndarray,
    labels: list[str],
    k: int = 10,
    *,
    albums: list[str] | None = None,
    genres: list[str] | None = None,
    head_scores: list[list[float]] | None = None,
    head_names: list[str] | None = None,
    sids: list[str] | None = None,
) -> dict:
    """Compute MAP@k, MRR, NDCG@k, Recall@k and discrimination scores.

    Returns a dict with three families of retrieval metrics plus discrimination
    and within/cross similarity statistics.

    Retrieval metrics — artist (``labels``):
      map_k_artist   : MAP@k
      mrr            : mean reciprocal rank
      ndcg_k_artist  : NDCG@k
      recall_k_artist: Recall@k

    Retrieval metrics — genre (requires ``genres``; ``None`` if not provided):
      map_k_genre    : MAP@k over genre labels
      mrr_genre      : MRR over genre labels
      ndcg_k_genre   : NDCG@k over genre labels
      recall_k_genre : Recall@k over genre labels
      precision_k_genre: mean precision@k over genre labels
      ap_k_genre     : list[float] of per-song AP@k (genre), length n

    Retrieval metrics — head (requires ``head_scores``; ``None`` if not provided):
      map_k_head     : MAP@k averaged across heads
      mrr_head       : MRR averaged across heads
      ndcg_k_head    : NDCG@k averaged across heads
      recall_k_head  : Recall@k averaged across heads
      ap_k_head      : list[float] of per-song AP@k (head), length n

    Discrimination metrics (mean within-group sim minus mean cross-group sim,
    computed over upper-triangle pairs):
      disc_artist    : artist-level discrimination (``labels``)
      disc_genre     : genre-level; 0.0 if ``genres`` not provided or unusable
      disc_head      : window-based discrimination — mean over heads of
                       (in-set mean - out-set mean), where in-set = songs within
                       DISC_HEAD_WINDOW of the query head score, out-set = songs
                       below score_i - DISC_HEAD_GAP
      disc_general   : mean of whichever disc components had valid data
      per_head_corr  : dict[head_name, corr] — Spearman r per head (empty if
                       ``head_names`` absent)

    ``disc_score`` is preserved as an alias of ``disc_artist`` for back-compat.

    Within/cross similarity statistics (artist, genre, head):
      mean_within_artist, var_within_artist : mean and variance of within-artist
                       pair similarities (upper triangle)
      mean_cross_artist, var_cross_artist   : mean and variance of cross-artist
                       pair similarities
      mean_within, mean_cross               : back-compat aliases for the artist
                       within/cross means
      mean_within_genre, var_within_genre,
      mean_cross_genre, var_cross_genre     : same for genre pairs; ``None`` if
                       ``genres`` not provided
      mean_within_head, var_within_head,
      mean_cross_head, var_cross_head       : same for head-score-defined pairs
                       (within = |score diff| ≤ DISC_HEAD_WINDOW across any head);
                       ``None`` if ``head_scores`` not provided

    ``sids``, when provided, enables per-song breakdowns: the returned dict gains a
    ``"per_song"`` key containing ``song_ids``, ``ap_k``, ``mrr``, ``recall_k``,
    ``disc_artist_contrib``, ``disc_genre_contrib``, ``disc_head_contrib``,
    ``ap_k_genre``, ``mrr_genre``, ``ap_k_head``, and ``mrr_head`` lists,
    each aligned by index to ``song_ids``.
    """
    n = len(labels)
    label_arr = np.array(labels)
    rankings = _rankings_from_sim(sim_matrix)

    aps, rrs, ndcgs, recalls = [], [], [], []
    _ps_ap: list[float] = []
    _ps_mrr: list[float] = []
    _ps_recall: list[float] = []
    within_sims: list[float] = []
    cross_sims: list[float] = []
    genre_arr = np.array(genres) if (genres is not None and len(genres) == n) else None
    _ps_ap_genre: list[float] = []
    _ps_mrr_genre: list[float] = []
    aps_genre: list[float] = []
    rrs_genre: list[float] = []
    ndcgs_genre: list[float] = []
    recalls_genre: list[float] = []
    within_sims_genre: list[float] = []
    cross_sims_genre: list[float] = []
    _ps_ap_head: list[float] = []
    _ps_mrr_head: list[float] = []

    def _dcg(hits_arr: list[int]) -> float:
        return sum(h / np.log2(r + 2) for r, h in enumerate(hits_arr))

    for i in range(n):
        relevant_set = {j for j in range(n) if j != i and label_arr[j] == label_arr[i]}
        if not relevant_set:
            _ps_ap.append(0.0)
            _ps_mrr.append(0.0)
            _ps_recall.append(0.0)
            continue
        ranked = rankings[i]
        ranked_k = ranked[:k]

        # AP@k
        hits = 0
        ap = 0.0
        for rank, idx in enumerate(ranked_k, 1):
            if idx in relevant_set:
                hits += 1
                ap += hits / rank
        denom = min(k, len(relevant_set))
        ap_value = ap / denom if denom > 0 else 0.0
        _ps_ap.append(ap_value)
        aps.append(ap_value)

        # MRR
        first_rel = next((r for r, idx in enumerate(ranked, 1) if idx in relevant_set), n)
        mrr_value = 1.0 / first_rel
        _ps_mrr.append(mrr_value)
        rrs.append(mrr_value)

        # NDCG@k — skip if fewer than 2 relevant docs (sklearn requires > 1 document)
        n_rel = len(relevant_set)
        if _SKLEARN:
            true_rel_list = [1 if idx in relevant_set else 0 for idx in ranked[:k]]
            # Pad to exactly k so shapes match ideal_rel
            if len(true_rel_list) < k:
                true_rel_list += [0] * (k - len(true_rel_list))
            true_rel = np.array(true_rel_list)
            ideal_rel = np.concatenate([np.ones(min(k, n_rel)), np.zeros(max(0, k - n_rel))])
            if len(ideal_rel) > 1:
                ndcgs.append(float(_sklearn_ndcg(ideal_rel[None, :], true_rel[None, :])))
        else:
            actual_hits = [1 if ranked[r] in relevant_set else 0 for r in range(min(k, n - 1))]
            ideal_hits = [1] * min(k, n_rel) + [0] * max(0, k - n_rel)
            ideal = _dcg(ideal_hits)
            ndcgs.append(_dcg(actual_hits) / ideal if ideal > 0 else 0.0)

        # Recall@k (artist)
        top_k_set = set(ranked[:k].tolist())
        recall_value = len(top_k_set & relevant_set) / min(k, n_rel)
        _ps_recall.append(recall_value)
        recalls.append(recall_value)

        # Discrimination
        for j in range(i + 1, n):
            s = float(sim_matrix[i, j])
            (within_sims if label_arr[j] == label_arr[i] else cross_sims).append(s)
            if genre_arr is not None:
                (within_sims_genre if genre_arr[j] == genre_arr[i] else cross_sims_genre).append(s)

    disc = float(np.mean(within_sims) - np.mean(cross_sims)) if within_sims and cross_sims else 0.0
    var_within_artist = float(np.var(within_sims)) if within_sims else 0.0
    var_cross_artist = float(np.var(cross_sims)) if cross_sims else 0.0

    disc_artist_contrib_per_song: list[float | None] = []
    for i in range(n):
        within = [j for j in range(n) if j != i and label_arr[j] == label_arr[i]]
        cross = [j for j in range(n) if label_arr[j] != label_arr[i]]
        if not within:
            disc_artist_contrib_per_song.append(None)
            continue
        disc_artist_contrib_per_song.append(float(sim_matrix[i, within].mean() - sim_matrix[i, cross].mean()))

    disc_genre_contrib_per_song: list[float | None]
    if genres is not None and len(genres) == n:
        genre_arr = np.array(genres)
        disc_genre_contrib_per_song = []
        for i in range(n):
            within = [j for j in range(n) if j != i and genre_arr[j] == genre_arr[i]]
            cross = [j for j in range(n) if genre_arr[j] != genre_arr[i]]
            if not within:
                disc_genre_contrib_per_song.append(None)
                continue
            disc_genre_contrib_per_song.append(float(sim_matrix[i, within].mean() - sim_matrix[i, cross].mean()))
    else:
        disc_genre_contrib_per_song = [None] * n

    # -- recall_k_album / recall_k_genre -----------------------------------
    album_recalls: list[float] = []
    if albums is not None and len(albums) == n:
        album_arr = np.array(albums)
        for i in range(n):
            album_rel = {j for j in range(n) if j != i and album_arr[j] == album_arr[i]}
            if not album_rel:
                continue
            top_k = set(rankings[i][:k].tolist())
            album_recalls.append(len(top_k & album_rel) / min(k, len(album_rel)))

    genre_recalls: list[float] = []
    genre_prec: list[float] = []
    if genres is not None and len(genres) == n:
        genre_arr_g = np.array(genres)
        for i in range(n):
            genre_rel = {j for j in range(n) if j != i and genre_arr_g[j] == genre_arr_g[i]}
            if not genre_rel:
                continue
            ranked_k = rankings[i][:k]
            top_k = set(ranked_k.tolist())
            genre_recalls.append(len(top_k & genre_rel) / min(k, len(genre_rel)))
            if len(ranked_k) > 0:
                genre_prec.append(float(np.mean(genre_arr_g[ranked_k] == genre_arr_g[i])))

    precision_k_genre = float(np.mean(genre_prec)) if genre_prec else 0.0

    if genre_arr is not None:
        for i in range(n):
            genre_rel_set = {j for j in range(n) if j != i and genre_arr[j] == genre_arr[i]}
            if not genre_rel_set:
                _ps_ap_genre.append(0.0)
                _ps_mrr_genre.append(0.0)
                continue
            ranked = rankings[i]
            ranked_k = ranked[:k]

            hits = 0
            ap = 0.0
            for rank, idx in enumerate(ranked_k, 1):
                if idx in genre_rel_set:
                    hits += 1
                    ap += hits / rank
            denom = min(k, len(genre_rel_set))
            ap_value = ap / denom if denom > 0 else 0.0
            _ps_ap_genre.append(ap_value)
            aps_genre.append(ap_value)

            first_rel = next((r for r, idx in enumerate(ranked, 1) if idx in genre_rel_set), n)
            mrr_value = 1.0 / first_rel
            _ps_mrr_genre.append(mrr_value)
            rrs_genre.append(mrr_value)

            n_rel_genre = len(genre_rel_set)
            if _SKLEARN:
                true_rel_list = [1 if idx in genre_rel_set else 0 for idx in ranked[:k]]
                if len(true_rel_list) < k:
                    true_rel_list += [0] * (k - len(true_rel_list))
                true_rel = np.array(true_rel_list)
                ideal_rel = np.concatenate([np.ones(min(k, n_rel_genre)), np.zeros(max(0, k - n_rel_genre))])
                if len(ideal_rel) > 1:
                    ndcgs_genre.append(float(_sklearn_ndcg(ideal_rel[None, :], true_rel[None, :])))
            else:
                actual_hits = [1 if ranked[r] in genre_rel_set else 0 for r in range(min(k, n - 1))]
                ideal_hits = [1] * min(k, n_rel_genre) + [0] * max(0, k - n_rel_genre)
                ideal = _dcg(ideal_hits)
                ndcgs_genre.append(_dcg(actual_hits) / ideal if ideal > 0 else 0.0)

            recall_value = len(set(ranked[:k].tolist()) & genre_rel_set) / min(k, n_rel_genre)
            recalls_genre.append(recall_value)

    if within_sims_genre or cross_sims_genre:
        mean_within_genre: float | None = float(np.mean(within_sims_genre)) if within_sims_genre else None
        var_within_genre: float | None = float(np.var(within_sims_genre)) if within_sims_genre else None
        mean_cross_genre: float | None = float(np.mean(cross_sims_genre)) if cross_sims_genre else None
        var_cross_genre: float | None = float(np.var(cross_sims_genre)) if cross_sims_genre else None
    else:
        mean_within_genre = var_within_genre = mean_cross_genre = var_cross_genre = None

    def _disc_from_groups(groups: list[str] | None) -> float:
        if groups is None or len(groups) != n:
            return 0.0
        g = np.asarray(groups)
        eye = np.eye(n, dtype=bool)
        within_mask = (g[:, None] == g[None, :]) & ~eye
        cross_mask = g[:, None] != g[None, :]
        if within_mask.any() and cross_mask.any():
            return float(sim_matrix[within_mask].mean() - sim_matrix[cross_mask].mean())
        return 0.0

    # -- disc_genre ---------------------------------------------------------
    disc_genre = _disc_from_groups(genres)

    # -- disc_head: window-based score-neighborhood discrimination -----------
    disc_head = 0.0
    map_k_head = mrr_head = ndcg_k_head = recall_k_head = None
    mean_within_head = var_within_head = mean_cross_head = var_cross_head = None
    per_head_corr: dict[str, float] = {}
    head_score_matrix: np.ndarray | None = None
    if head_scores is not None:
        head_scores_arr = np.asarray(head_scores, dtype=np.float64)
        if head_scores_arr.ndim == 2:
            if head_scores_arr.shape[1] == n and head_scores_arr.shape[0] > 0:
                head_score_matrix = head_scores_arr
            elif head_scores_arr.shape[0] == n and head_scores_arr.shape[1] > 0:
                head_score_matrix = head_scores_arr.T

    disc_head_contrib_per_song: list[float | None] = [None] * n
    _ps_head_all: list[list[float]] = [[] for _ in range(n)]
    _ps_ap_head_all: list[list[float]] = [[] for _ in range(n)]
    _ps_mrr_head_all: list[list[float]] = [[] for _ in range(n)]
    if head_score_matrix is not None and head_score_matrix.shape[0] > 0:
        iu, ju = np.triu_indices(n, k=1)
        sim_pairs = sim_matrix[iu, ju].astype(np.float64)
        per_head_disc_values: list[float] = []
        per_head_map_vals: list[float] = []
        per_head_mrr_vals: list[float] = []
        per_head_ndcg_vals: list[float] = []
        per_head_recall_vals: list[float] = []

        for h_idx, h_scores in enumerate(head_score_matrix):
            contribs: list[float] = []
            for i in range(n):
                score_i = float(h_scores[i])
                in_mask = np.abs(h_scores - score_i) <= DISC_HEAD_WINDOW
                out_mask = np.abs(h_scores - score_i) > (DISC_HEAD_WINDOW + DISC_HEAD_GAP)
                in_mask[i] = False
                out_mask[i] = False
                if not in_mask.any() or not out_mask.any():
                    continue
                contrib = sim_matrix[i, in_mask].mean() - sim_matrix[i, out_mask].mean()
                contribs.append(float(contrib))
                _ps_head_all[i].append(float(contrib))
            if contribs:
                per_head_disc_values.append(float(np.mean(contribs)))

            # per-head individual Spearman correlations (kept for head-sim-corr section)
            if head_names is not None and len(head_names) == head_score_matrix.shape[0]:
                h_diff = np.abs(h_scores[iu] - h_scores[ju]).astype(np.float64)
                if sim_pairs.std() > 0 and h_diff.std() > 0:
                    r1h = np.argsort(np.argsort(sim_pairs))
                    r2h = np.argsort(np.argsort(-h_diff))
                    with np.errstate(invalid="ignore"):
                        ch = np.corrcoef(r1h, r2h)
                    if ch.shape == (2, 2) and not np.isnan(ch[0, 1]):
                        per_head_corr[head_names[h_idx]] = float(ch[0, 1])
                        continue
                per_head_corr[head_names[h_idx]] = 0.0

        disc_head_contrib_per_song = [float(np.mean(v)) if v else None for v in _ps_head_all]

        for _h_idx, h_scores in enumerate(head_score_matrix):
            head_aps: list[float] = []
            head_rrs: list[float] = []
            head_ndcgs: list[float] = []
            head_recalls: list[float] = []

            for i in range(n):
                head_rel_set = {
                    j for j in range(n) if j != i and abs(float(h_scores[j]) - float(h_scores[i])) <= DISC_HEAD_WINDOW
                }
                if not head_rel_set:
                    continue

                ranked = rankings[i]
                ranked_k = ranked[:k]

                hits = 0
                ap = 0.0
                for rank, idx in enumerate(ranked_k, 1):
                    if idx in head_rel_set:
                        hits += 1
                        ap += hits / rank
                denom = min(k, len(head_rel_set))
                ap_value = ap / denom if denom > 0 else 0.0
                head_aps.append(ap_value)
                _ps_ap_head_all[i].append(ap_value)

                first_rel = next((r for r, idx in enumerate(ranked, 1) if idx in head_rel_set), n)
                mrr_value = 1.0 / first_rel
                head_rrs.append(mrr_value)
                _ps_mrr_head_all[i].append(mrr_value)

                n_rel_head = len(head_rel_set)
                if _SKLEARN:
                    true_rel_list = [1 if idx in head_rel_set else 0 for idx in ranked[:k]]
                    if len(true_rel_list) < k:
                        true_rel_list += [0] * (k - len(true_rel_list))
                    true_rel = np.array(true_rel_list)
                    ideal_rel = np.concatenate([np.ones(min(k, n_rel_head)), np.zeros(max(0, k - n_rel_head))])
                    if len(ideal_rel) > 1:
                        head_ndcgs.append(float(_sklearn_ndcg(ideal_rel[None, :], true_rel[None, :])))
                else:
                    actual_hits = [1 if ranked[r] in head_rel_set else 0 for r in range(min(k, n - 1))]
                    ideal_hits = [1] * min(k, n_rel_head) + [0] * max(0, k - n_rel_head)
                    ideal = _dcg(ideal_hits)
                    head_ndcgs.append(_dcg(actual_hits) / ideal if ideal > 0 else 0.0)

                recall_value = len(set(ranked_k.tolist()) & head_rel_set) / min(k, n_rel_head)
                head_recalls.append(recall_value)

            if head_aps:
                per_head_map_vals.append(float(np.mean(head_aps)))
            if head_rrs:
                per_head_mrr_vals.append(float(np.mean(head_rrs)))
            if head_ndcgs:
                per_head_ndcg_vals.append(float(np.mean(head_ndcgs)))
            if head_recalls:
                per_head_recall_vals.append(float(np.mean(head_recalls)))

        _ps_ap_head = [float(np.mean(v)) if v else 0.0 for v in _ps_ap_head_all]
        _ps_mrr_head = [float(np.mean(v)) if v else 0.0 for v in _ps_mrr_head_all]
        map_k_head = float(np.mean(per_head_map_vals)) if per_head_map_vals else None
        mrr_head = float(np.mean(per_head_mrr_vals)) if per_head_mrr_vals else None
        ndcg_k_head = float(np.mean(per_head_ndcg_vals)) if per_head_ndcg_vals else None
        recall_k_head = float(np.mean(per_head_recall_vals)) if per_head_recall_vals else None

        head_pair_diffs = np.abs(head_score_matrix[:, iu] - head_score_matrix[:, ju]).astype(np.float64)
        within_sims_head = sim_pairs[np.any(head_pair_diffs <= DISC_HEAD_WINDOW, axis=0)].tolist()
        cross_sims_head = sim_pairs[np.all(head_pair_diffs > (DISC_HEAD_WINDOW + DISC_HEAD_GAP), axis=0)].tolist()
        mean_within_head = float(np.mean(within_sims_head)) if within_sims_head else None
        var_within_head = float(np.var(within_sims_head)) if within_sims_head else None
        mean_cross_head = float(np.mean(cross_sims_head)) if cross_sims_head else None
        var_cross_head = float(np.var(cross_sims_head)) if cross_sims_head else None

        disc_head = float(np.mean(per_head_disc_values)) if per_head_disc_values else 0.0

    # -- disc_general: mean of all non-zero disc components -------------------
    # Averages whichever components had enough data to produce a meaningful value.
    # Degrades gracefully: corpus with only artist labels → disc_general == disc_artist.
    _disc_components = [v for v in (disc, disc_genre, disc_head) if v != 0.0]
    if disc == 0.0:
        _log.warning(
            "[disc_general] disc_artist=0 — all songs same artist or corpus too small for artist-level separation",
        )
    if disc_genre == 0.0:
        if genres is None or len(genres) != n:
            _log.info("[disc_general] disc_genre=0 — no genre tags in corpus")
        else:
            _log.warning("[disc_general] disc_genre=0 despite genre data present — all songs same genre?")
    if disc_head == 0.0:
        _no_head_data = head_scores is None or (hasattr(head_scores, "__len__") and len(head_scores) == 0)
        if _no_head_data:
            _log.info("[disc_general] disc_head=0 — head scores not provided")
        else:
            _log.warning(
                "[disc_general] disc_head=0 despite head scores present — no valid score windows produced contributions",
            )
    disc_general = float(np.mean(_disc_components)) if _disc_components else 0.0

    return {
        "map_k_artist": float(np.mean(aps)) if aps else 0.0,
        "mrr": float(np.mean(rrs)) if rrs else 0.0,
        "map_k_genre": float(np.mean(aps_genre)) if aps_genre else (0.0 if genre_arr is not None else None),
        "mrr_genre": float(np.mean(rrs_genre)) if rrs_genre else (0.0 if genre_arr is not None else None),
        "ndcg_k_genre": float(np.mean(ndcgs_genre)) if ndcgs_genre else (0.0 if genre_arr is not None else None),
        "map_k_head": map_k_head,
        "mrr_head": mrr_head,
        "ndcg_k_head": ndcg_k_head,
        "ndcg_k_artist": float(np.mean(ndcgs)) if ndcgs else 0.0,
        "recall_k_artist": float(np.mean(recalls)) if recalls else 0.0,
        "recall_k_genre": float(np.mean(recalls_genre)) if recalls_genre else (0.0 if genre_arr is not None else None),
        "recall_k_head": recall_k_head,
        "precision_k_genre": precision_k_genre,
        "ap_k_genre": _ps_ap_genre,
        "ap_k_head": _ps_ap_head,
        "disc_score": disc,
        "disc_artist": disc,
        "disc_genre": disc_genre,
        "disc_head": disc_head,
        "disc_general": disc_general,
        "per_head_corr": per_head_corr,
        "mean_within_artist": float(np.mean(within_sims)) if within_sims else 0.0,
        "var_within_artist": var_within_artist,
        "mean_cross_artist": float(np.mean(cross_sims)) if cross_sims else 0.0,
        "var_cross_artist": var_cross_artist,
        "mean_within": float(np.mean(within_sims)) if within_sims else 0.0,
        "mean_cross": float(np.mean(cross_sims)) if cross_sims else 0.0,
        "mean_within_genre": mean_within_genre,
        "var_within_genre": var_within_genre,
        "mean_cross_genre": mean_cross_genre,
        "var_cross_genre": var_cross_genre,
        "mean_within_head": mean_within_head,
        "var_within_head": var_within_head,
        "mean_cross_head": mean_cross_head,
        "var_cross_head": var_cross_head,
        "per_song": {
            "song_ids": list(sids) if sids is not None else [str(i) for i in range(n)],
            "ap_k": _ps_ap,
            "mrr": _ps_mrr,
            "recall_k": _ps_recall,
            "disc_artist_contrib": disc_artist_contrib_per_song,
            "disc_genre_contrib": disc_genre_contrib_per_song,
            "disc_head_contrib": disc_head_contrib_per_song,
            "ap_k_genre": _ps_ap_genre,
            "mrr_genre": _ps_mrr_genre,
            "ap_k_head": _ps_ap_head,
            "mrr_head": _ps_mrr_head,
        },
    }
