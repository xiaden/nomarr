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
    return vecs / np.where(norms == 0, 1.0, norms)


# -- Pairwise similarity / distance matrices --------------------------------


def cosine_matrix(vecs: np.ndarray) -> np.ndarray:
    """[n, n] cosine similarity matrix."""
    normed = l2_normalise(vecs.astype(np.float32))
    return (normed @ normed.T).astype(np.float32)


def l2_similarity_matrix(vecs: np.ndarray) -> np.ndarray:
    """[n, n] Euclidean distance -> similarity: 1 / (1 + d)."""
    vf = vecs.astype(np.float32)
    sq = np.sum(vf**2, axis=1)
    dist2 = sq[:, None] + sq[None, :] - 2.0 * (vf @ vf.T)
    dist2 = np.maximum(dist2, 0.0)
    return (1.0 / (1.0 + np.sqrt(dist2))).astype(np.float32)


def dot_matrix(vecs: np.ndarray) -> np.ndarray:
    """[n, n] raw inner product matrix."""
    return vecs.astype(np.float32) @ vecs.astype(np.float32).T


METRICS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "cosine": cosine_matrix,
    "l2": l2_similarity_matrix,
    "dot": dot_matrix,
}


# -- Retrieval helper -------------------------------------------------------


def _rankings_from_sim(sim_matrix: np.ndarray) -> np.ndarray:
    """[n, n-1] sorted descending indices, self excluded."""
    n = sim_matrix.shape[0]
    out = np.empty((n, n - 1), dtype=np.int32)
    for i in range(n):
        row = sim_matrix[i].copy()
        row[i] = -np.inf
        out[i] = np.argsort(-row)
    return out


def compute_retrieval_metrics(
    sim_matrix: np.ndarray,
    labels: list[str],
    k: int = 10,
) -> dict[str, float]:
    """
    MAP@k, MRR, NDCG@k, Recall@k, discrimination score.
    Relevance = same artist label.
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
        hits = ap = 0
        for rank, idx in enumerate(ranked, 1):
            if idx in relevant_set:
                hits += 1
                ap += hits / rank
        aps.append(ap / len(relevant_set))

        # MRR
        first_rel = next((r for r, idx in enumerate(ranked, 1) if idx in relevant_set), n)
        rrs.append(1.0 / first_rel)

        # NDCG@k
        n_rel = len(relevant_set)
        if _SKLEARN:
            true_rel = np.array([1 if idx in relevant_set else 0 for idx in ranked[:k]])
            ideal_rel = np.concatenate([np.ones(min(k, n_rel)), np.zeros(max(0, k - n_rel))])
            ndcgs.append(float(_sklearn_ndcg(ideal_rel[None, :], true_rel[None, :])))
        else:

            def _dcg(hits_arr):
                return sum(h / np.log2(r + 2) for r, h in enumerate(hits_arr))

            actual_hits = [1 if ranked[r] in relevant_set else 0 for r in range(min(k, n - 1))]
            ideal_hits = [1] * min(k, n_rel) + [0] * max(0, k - n_rel)
            ideal = _dcg(ideal_hits)
            ndcgs.append(_dcg(actual_hits) / ideal if ideal > 0 else 0.0)

        # Recall@k
        top_k_set = set(ranked[:k].tolist())
        recalls.append(len(top_k_set & relevant_set) / min(k, n_rel))

        # Discrimination
        for j in range(i + 1, n):
            s = float(sim_matrix[i, j])
            (within_sims if label_arr[j] == label_arr[i] else cross_sims).append(s)

    disc = float(np.mean(within_sims) - np.mean(cross_sims)) if within_sims and cross_sims else 0.0

    return {
        f"map_{k}": float(np.mean(aps)) if aps else 0.0,
        "mrr": float(np.mean(rrs)) if rrs else 0.0,
        f"ndcg_{k}": float(np.mean(ndcgs)) if ndcgs else 0.0,
        f"recall_{k}": float(np.mean(recalls)) if recalls else 0.0,
        "disc_score": disc,
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
                _, I = self._index.search(qn[None, :], k)
            else:
                _, I = self._index.search(qvec[None, :], k)
            return I[0]
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
