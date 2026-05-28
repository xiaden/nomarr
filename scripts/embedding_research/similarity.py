"""
Similarity metrics and retrieval quality measures.

Metrics:
  cosine  - cosine similarity (direction only; L2-normalised dot product)
  l2      - Euclidean distance converted to similarity: 1 / (1 + d)
  dot     - raw inner product (meaningful only for L2-normalised vectors)

ANN back-ends (preferred order, auto-selected):
  1. faiss (HNSW flat index on cosine / L2)
  2. numpy brute-force (always available)

Retrieval metrics:
  MAP@k, MRR, NDCG@k, Recall@k computed over artist-level labels.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Callable

import numpy as np

from .vector_types import RawTensor, RawVector, UnitTensor

_log = logging.getLogger(__name__)

try:
    import faiss

    _FAISS = True
except ImportError:
    _FAISS = False
    warnings.warn("faiss not installed -- ANN will use numpy brute-force.", stacklevel=1)

try:
    from sklearn.metrics import ndcg_score as _sklearn_ndcg

    _SKLEARN = True
except ImportError:
    _SKLEARN = False


# -- L2-normalisation -------------------------------------------------------


def l2_normalise(vecs: RawTensor) -> UnitTensor:
    """Return unit-norm vectors [n, d]."""
    return vecs.normalize()


# -- Pairwise similarity / distance matrices --------------------------------


def cosine_matrix(vecs: RawTensor) -> np.ndarray:
    """[n, n] cosine similarity matrix."""
    normed = vecs.normalize().data
    return np.asarray((normed @ normed.T).astype(np.float32))


def l2_similarity_matrix(vecs: RawTensor) -> np.ndarray:
    """[n, n] Euclidean distance -> similarity: 1 / (1 + d)."""
    vf = vecs.data
    sq = np.sum(vf**2, axis=1)
    dist2 = sq[:, None] + sq[None, :] - 2.0 * (vf @ vf.T)
    dist2 = np.maximum(dist2, 0.0)
    return np.asarray((1.0 / (1.0 + np.sqrt(dist2))).astype(np.float32))


# dot omitted: on L2-normalised vectors it equals cosine; no additional signal.
METRICS: dict[str, Callable[[RawTensor], np.ndarray]] = {
    "cosine": cosine_matrix,
    "l2": l2_similarity_matrix,
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
) -> dict:
    """
    MAP@k, MRR, NDCG@k, Recall@k, and discrimination scores.

    Discrimination metrics (mean within-group sim minus mean cross-group sim,
    computed over upper-triangle pairs):
      disc_artist    : labels (artist)
      disc_album     : optional albums list; 0.0 if not provided or unusable
      disc_genre     : optional genres list (real tag); 0.0 if not provided or unusable
      disc_head      : Spearman rank corr of sim vs mean-abs head-score diff (collapsed average)
      per_head_corr  : dict[head_name, corr] — individual Spearman r per head (empty if head_names absent)

    `disc_score` is preserved as an alias of `disc_artist` for back-compat.
    """
    n = len(labels)
    label_arr = np.array(labels)
    rankings = _rankings_from_sim(sim_matrix)

    aps, rrs, ndcgs, recalls = [], [], [], []
    within_sims: list[float] = []
    cross_sims: list[float] = []

    for i in range(n):
        relevant_set = {j for j in range(n) if j != i and label_arr[j] == label_arr[i]}
        if not relevant_set:
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
        aps.append(ap / denom if denom > 0 else 0.0)

        # MRR
        first_rel = next((r for r, idx in enumerate(ranked, 1) if idx in relevant_set), n)
        rrs.append(1.0 / first_rel)

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

            def _dcg(hits_arr):
                return sum(h / np.log2(r + 2) for r, h in enumerate(hits_arr))

            actual_hits = [1 if ranked[r] in relevant_set else 0 for r in range(min(k, n - 1))]
            ideal_hits = [1] * min(k, n_rel) + [0] * max(0, k - n_rel)
            ideal = _dcg(ideal_hits)
            ndcgs.append(_dcg(actual_hits) / ideal if ideal > 0 else 0.0)

        # Recall@k (artist)
        top_k_set = set(ranked[:k].tolist())
        recalls.append(len(top_k_set & relevant_set) / min(k, n_rel))

        # Discrimination
        for j in range(i + 1, n):
            s = float(sim_matrix[i, j])
            (within_sims if label_arr[j] == label_arr[i] else cross_sims).append(s)

    disc = float(np.mean(within_sims) - np.mean(cross_sims)) if within_sims and cross_sims else 0.0

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

    # -- disc_head: fixed-width score-bin discrimination ---------------------
    disc_head = 0.0
    precision_k_head_mean = 0.0
    per_head_corr: dict[str, float] = {}
    head_score_matrix: np.ndarray | None = None
    if head_scores is not None:
        head_scores_arr = np.asarray(head_scores, dtype=np.float64)
        if head_scores_arr.ndim == 2:
            if head_scores_arr.shape[1] == n and head_scores_arr.shape[0] > 0:
                head_score_matrix = head_scores_arr
            elif head_scores_arr.shape[0] == n and head_scores_arr.shape[1] > 0:
                head_score_matrix = head_scores_arr.T

    if head_score_matrix is not None and head_score_matrix.shape[0] > 0:
        iu, ju = np.triu_indices(n, k=1)
        sim_pairs = sim_matrix[iu, ju].astype(np.float64)
        per_head_disc_values: list[float] = []
        head_prec_means: list[float] = []

        for h_idx, h_scores in enumerate(head_score_matrix):
            bin_idx = np.minimum((h_scores * 10).astype(np.int32), 9)
            if not np.all(bin_idx == bin_idx[0]):
                per_head_disc_values.append(_disc_from_groups([str(b) for b in bin_idx.tolist()]))
            else:
                _log.info(
                    "[disc_head] head %d skipped — all %d songs landed in bin %d (constant distribution)",
                    h_idx,
                    n,
                    int(bin_idx[0]),
                )

            head_prec: list[float] = []
            for i in range(n):
                ranked_k = rankings[i][:k]
                if len(ranked_k) == 0:
                    continue
                head_prec.append(float(np.mean(bin_idx[ranked_k] == bin_idx[i])))
            if head_prec:
                head_prec_means.append(float(np.mean(head_prec)))

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

        disc_head = float(np.mean(per_head_disc_values)) if per_head_disc_values else 0.0
        precision_k_head_mean = float(np.mean(head_prec_means)) if head_prec_means else 0.0

    # -- disc_general: mean of all non-zero disc components -------------------
    # Averages whichever components had enough data to produce a meaningful value.
    # Degrades gracefully: corpus with only artist labels → disc_general == disc_artist.
    _disc_components = [v for v in (disc, disc_genre, disc_head) if v != 0.0]
    if disc == 0.0:
        _log.warning(
            "[disc_general] disc_artist=0 — all songs same artist or corpus too small for artist-level separation"
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
            _log.warning("[disc_general] disc_head=0 despite head scores present — all songs in same score bin?")
    disc_general = float(np.mean(_disc_components)) if _disc_components else 0.0

    return {
        f"map_{k}": float(np.mean(aps)) if aps else 0.0,
        "mrr": float(np.mean(rrs)) if rrs else 0.0,
        f"ndcg_{k}": float(np.mean(ndcgs)) if ndcgs else 0.0,
        f"recall_{k}": float(np.mean(recalls)) if recalls else 0.0,
        f"recall_{k}_genre": float(np.mean(genre_recalls)) if genre_recalls else 0.0,
        "precision_k_genre": precision_k_genre,
        "precision_k_head_mean": precision_k_head_mean,
        "disc_score": disc,
        "disc_artist": disc,
        "disc_genre": disc_genre,
        "disc_head": disc_head,
        "disc_general": disc_general,
        "per_head_corr": per_head_corr,
        "mean_within": float(np.mean(within_sims)) if within_sims else 0.0,
        "mean_cross": float(np.mean(cross_sims)) if cross_sims else 0.0,
    }


# -- FAISS ANN index --------------------------------------------------------


class ANNIndex:
    """
    Wraps faiss HNSW (cosine) and IVF (L2) indices, with a numpy brute-force
    fallback when faiss is not installed.

    Usage:
        idx = ANNIndex(vecs, metric="cosine")
        top_k = idx.query(query_vec, k=10)       # [k] indices
        recall = idx.recall_at_k(exact_top_k, k=10)
    """

    SUPPORTED_METRICS = ("cosine", "l2")

    def __init__(
        self,
        vecs: RawTensor,
        metric: str = "cosine",
        hnsw_m: int = 32,
        hnsw_ef_construction: int = 200,
        hnsw_ef_search: int = 64,
        nlist: int = 100,
    ):
        assert metric in self.SUPPORTED_METRICS
        self.metric = metric
        self.n, self.d = vecs.data.shape
        self._vecs = vecs.data.copy()
        self._hnsw_ef_search = hnsw_ef_search
        self._built_with = "faiss" if _FAISS else "numpy"
        self._index = None

        if _FAISS:
            self._build_faiss(hnsw_m, hnsw_ef_construction, hnsw_ef_search, nlist)

    def _build_faiss(self, hnsw_m, hnsw_ef_construction, hnsw_ef_search, nlist):
        if self.metric == "cosine":
            normed = l2_normalise(RawTensor(self._vecs)).data
            index = faiss.IndexHNSWFlat(self.d, hnsw_m, faiss.METRIC_INNER_PRODUCT)
            index.hnsw.efConstruction = hnsw_ef_construction
            index.hnsw.efSearch = hnsw_ef_search
            index.add(normed)
            self._normed = normed
        else:
            if self.n > 4 * nlist:
                quantiser = faiss.IndexFlatL2(self.d)
                index = faiss.IndexIVFFlat(quantiser, self.d, nlist, faiss.METRIC_L2)
                index.train(self._vecs)
                index.nprobe = max(1, nlist // 10)
            else:
                index = faiss.IndexFlatL2(self.d)
            index.add(self._vecs)
        self._index = index

    def set_ef_search(self, ef: int) -> None:
        self._hnsw_ef_search = ef
        if _FAISS and self._index and self.metric == "cosine":
            self._index.hnsw.efSearch = ef

    def query(self, qvec: RawVector, k: int) -> np.ndarray:
        """Return [k] indices of approximate nearest neighbours."""
        qvec_np = qvec.data
        if _FAISS and self._index is not None:
            if self.metric == "cosine":
                qn = l2_normalise(RawTensor(qvec_np[None, :])).data[0]
                _, nn_idx = self._index.search(qn[None, :], k)
            else:
                _, nn_idx = self._index.search(qvec_np[None, :], k)
            return nn_idx[0]
        # numpy fallback
        if self.metric == "cosine":
            normed = l2_normalise(RawTensor(self._vecs)).data
            qn = l2_normalise(RawTensor(qvec_np[None, :])).data[0]
            sims = normed @ qn
            return np.argsort(-sims)[:k]
        dists = np.linalg.norm(self._vecs - qvec_np, axis=1)
        return np.argsort(dists)[:k]

    def recall_at_k(
        self,
        exact_top_k: dict[int, list[int]],
        k: int,
        query_indices: list[int] | None = None,
    ) -> float:
        """Mean recall@k of this index vs brute-force exact top-k."""
        qidxs = query_indices or list(exact_top_k)
        recalls = []
        for qi in qidxs:
            exact = set(exact_top_k[qi][:k])
            approx = set(self.query(RawVector(self._vecs[qi]), k + 1).tolist())
            approx.discard(qi)
            recalls.append(len(approx & exact) / k)
        return float(np.mean(recalls))


# -- ANN recall vs ef_search sweep -----------------------------------------


def ann_recall_sweep(
    vecs: RawTensor,
    labels: list[str],
    k: int = 10,
    n_queries: int = 200,
    ef_values: list[int] | None = None,
    recall_target: float = 0.995,
) -> dict:
    """
    Measure ANN recall@k as ef_search increases (cosine HNSW).
    Returns {"ef_{ef}": {"recall_k": float, "backend": "faiss"|"numpy"}}

    Stops early once recall >= recall_target — no need to test higher ef values
    once the index is already accurate enough.
    """
    if ef_values is None:
        ef_values = [16, 32, 64, 128, 256]

    rng = np.random.RandomState(42)
    n = vecs.data.shape[0]
    query_idx = list(rng.choice(n, size=min(n_queries, n), replace=False))

    cos_mat = cosine_matrix(vecs)
    exact_top_k: dict[int, list[int]] = {}
    for qi in query_idx:
        row = cos_mat[qi].copy()
        row[qi] = -np.inf
        exact_top_k[qi] = list(np.argsort(-row)[:k])

    results = {}
    for ef in ef_values:
        idx = ANNIndex(vecs, metric="cosine", hnsw_ef_search=ef)
        recall = idx.recall_at_k(exact_top_k, k=k, query_indices=query_idx)
        results[f"ef_{ef}"] = {
            "recall_k": recall,
            "ef_search": ef,
            "backend": idx._built_with,
        }
        if recall >= recall_target:
            break  # no point testing higher ef values
    return results
