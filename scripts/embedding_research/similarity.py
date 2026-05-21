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

import warnings
from collections.abc import Callable

import numpy as np

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


def l2_normalise(vecs: np.ndarray) -> np.ndarray:
    """Return unit-norm vectors [n, d]."""
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return np.asarray(vecs / np.where(norms == 0, 1.0, norms))


# -- Pairwise similarity / distance matrices --------------------------------


def cosine_matrix(vecs: np.ndarray) -> np.ndarray:
    """[n, n] cosine similarity matrix."""
    normed = l2_normalise(vecs.astype(np.float32))
    return np.asarray((normed @ normed.T).astype(np.float32))


def l2_similarity_matrix(vecs: np.ndarray) -> np.ndarray:
    """[n, n] Euclidean distance -> similarity: 1 / (1 + d)."""
    vf = vecs.astype(np.float32)
    sq = np.sum(vf**2, axis=1)
    dist2 = sq[:, None] + sq[None, :] - 2.0 * (vf @ vf.T)
    dist2 = np.maximum(dist2, 0.0)
    return np.asarray((1.0 / (1.0 + np.sqrt(dist2))).astype(np.float32))


def dot_matrix(vecs: np.ndarray) -> np.ndarray:
    """[n, n] raw inner product matrix."""
    return vecs.astype(np.float32) @ vecs.astype(np.float32).T


# dot is excluded: on L2-normalised vectors it is identical to cosine.
# All callers normalise before passing in, so dot would add no signal.
METRICS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
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
        row[i] = -np.inf
        sorted_idx = np.argsort(-row)  # shape (n,)
        out[i] = sorted_idx[sorted_idx != i][: n - 1]  # drop self, take n-1
    return out


def compute_retrieval_metrics(
    sim_matrix: np.ndarray,
    labels: list[str],
    k: int = 10,
    *,
    albums: list[str] | None = None,
    genres: list[str] | None = None,
    head_scores: np.ndarray | None = None,
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

        # AP@k
        hits = 0
        ap = 0.0
        for rank, idx in enumerate(ranked, 1):
            if idx in relevant_set:
                hits += 1
                ap += hits / rank
        aps.append(ap / len(relevant_set))

        # MRR
        first_rel = next((r for r, idx in enumerate(ranked, 1) if idx in relevant_set), n)
        rrs.append(1.0 / first_rel)

        # NDCG@k — skip if fewer than 2 relevant docs (sklearn requires > 1 document)
        n_rel = len(relevant_set)
        if _SKLEARN:
            true_rel = np.array([1 if idx in relevant_set else 0 for idx in ranked[:k]])
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
    if genres is not None and len(genres) == n:
        genre_arr_g = np.array(genres)
        for i in range(n):
            genre_rel = {j for j in range(n) if j != i and genre_arr_g[j] == genre_arr_g[i]}
            if not genre_rel:
                continue
            top_k = set(rankings[i][:k].tolist())
            genre_recalls.append(len(top_k & genre_rel) / min(k, len(genre_rel)))

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

    # -- disc_album ---------------------------------------------------------
    disc_album = _disc_from_groups(albums)

    # -- disc_genre ---------------------------------------------------------
    disc_genre = _disc_from_groups(genres)

    # -- disc_head (Spearman rank corr of sim vs -mean head_distance) ----------
    disc_head = 0.0
    per_head_corr: dict[str, float] = {}
    if head_scores is not None and head_scores.shape[0] == n and head_scores.shape[1] > 0:
        iu, ju = np.triu_indices(n, k=1)
        sim_pairs = sim_matrix[iu, ju].astype(np.float64)

        # collapsed average across all heads
        head_diff = np.abs(head_scores[iu] - head_scores[ju]).mean(axis=1).astype(np.float64)
        if sim_pairs.std() > 0 and head_diff.std() > 0:
            r1 = np.argsort(np.argsort(sim_pairs))
            r2 = np.argsort(np.argsort(-head_diff))
            with np.errstate(invalid="ignore"):
                c = np.corrcoef(r1, r2)
            if c.shape == (2, 2) and not np.isnan(c[0, 1]):
                disc_head = float(c[0, 1])

        # per-head individual correlations
        if head_names is not None and len(head_names) == head_scores.shape[1]:
            for h_idx, h_name in enumerate(head_names):
                h_diff = np.abs(head_scores[iu, h_idx] - head_scores[ju, h_idx]).astype(np.float64)
                if sim_pairs.std() > 0 and h_diff.std() > 0:
                    r1h = np.argsort(np.argsort(sim_pairs))
                    r2h = np.argsort(np.argsort(-h_diff))
                    with np.errstate(invalid="ignore"):
                        ch = np.corrcoef(r1h, r2h)
                    if ch.shape == (2, 2) and not np.isnan(ch[0, 1]):
                        per_head_corr[h_name] = float(ch[0, 1])
                        continue
                per_head_corr[h_name] = 0.0

    return {
        f"map_{k}": float(np.mean(aps)) if aps else 0.0,
        "mrr": float(np.mean(rrs)) if rrs else 0.0,
        f"ndcg_{k}": float(np.mean(ndcgs)) if ndcgs else 0.0,
        f"recall_{k}": float(np.mean(recalls)) if recalls else 0.0,
        f"recall_{k}_album": float(np.mean(album_recalls)) if album_recalls else 0.0,
        f"recall_{k}_genre": float(np.mean(genre_recalls)) if genre_recalls else 0.0,
        "disc_score": disc,
        "disc_artist": disc,
        "disc_album": disc_album,
        "disc_genre": disc_genre,
        "disc_head": disc_head,
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
        vecs: np.ndarray,
        metric: str = "cosine",
        hnsw_m: int = 32,
        hnsw_ef_construction: int = 200,
        hnsw_ef_search: int = 64,
        nlist: int = 100,
    ):
        assert metric in self.SUPPORTED_METRICS
        self.metric = metric
        self.n, self.d = vecs.shape
        self._vecs = vecs.astype(np.float32).copy()
        self._hnsw_ef_search = hnsw_ef_search
        self._built_with = "faiss" if _FAISS else "numpy"
        self._index = None

        if _FAISS:
            self._build_faiss(hnsw_m, hnsw_ef_construction, hnsw_ef_search, nlist)

    def _build_faiss(self, hnsw_m, hnsw_ef_construction, hnsw_ef_search, nlist):
        if self.metric == "cosine":
            normed = l2_normalise(self._vecs)
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

    def query(self, qvec: np.ndarray, k: int) -> np.ndarray:
        """Return [k] indices of approximate nearest neighbours."""
        qvec = qvec.astype(np.float32)
        if _FAISS and self._index is not None:
            if self.metric == "cosine":
                qn = l2_normalise(qvec[None, :])[0]
                _, nn_idx = self._index.search(qn[None, :], k)
            else:
                _, nn_idx = self._index.search(qvec[None, :], k)
            return nn_idx[0]
        # numpy fallback
        if self.metric == "cosine":
            normed = l2_normalise(self._vecs)
            qn = l2_normalise(qvec[None, :])[0]
            sims = normed @ qn
            return np.argsort(-sims)[:k]
        dists = np.linalg.norm(self._vecs - qvec, axis=1)
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
            approx = set(self.query(self._vecs[qi], k + 1).tolist())
            approx.discard(qi)
            recalls.append(len(approx & exact) / k)
        return float(np.mean(recalls))


# -- ANN recall vs ef_search sweep -----------------------------------------


def ann_recall_sweep(
    vecs: np.ndarray,
    labels: list[str],
    k: int = 10,
    n_queries: int = 200,
    ef_values: list[int] | None = None,
) -> dict:
    """
    Measure ANN recall@k as ef_search increases (cosine HNSW).
    Returns {"ef_{ef}": {"recall_k": float, "backend": "faiss"|"numpy"}}
    """
    if ef_values is None:
        ef_values = [16, 32, 64, 128, 256]

    rng = np.random.RandomState(42)
    n = len(vecs)
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
    return results
