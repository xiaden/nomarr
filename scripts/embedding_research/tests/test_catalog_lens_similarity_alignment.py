"""Plan D round-1 fix — catalog metric lenses mirror ``similarity`` exactly.

Pins the catalog-first lens arithmetic (``catalog_analysis._Lenses`` and ``_ndcg_at_k``) to the LEGACY
metric authority ``similarity.compute_retrieval_metrics``:

* NDCG discounts a 1-based top-ranked hit by ``1/log2(rank + 1)`` (equivalent to ``similarity``'s
  ``h / log2(r + 2)`` over 0-based ``r``), so a single top-ranked relevant song is NDCG 1.0 — NOT the
  old ``log2(rank + 2)`` (== 0.6309) the lens previously used.
* MRR scans the FULL ranking (not k-truncated): a first same-artist hit beyond ``k`` still contributes
  ``1/rank``, matching ``similarity``'s full-matrix MRR.

The regression builds a FIXED synthetic per-query candidate ranking, evaluates the catalog lenses
over it via :class:`_Lenses`, and asserts the aggregate ``map_k`` / ``mrr`` / ``ndcg_k`` / ``recall_k``
equal ``similarity.compute_retrieval_metrics``' ``map_k_artist`` / ``mrr`` / ``ndcg_k_artist`` /
``recall_k_artist`` on the same ranking — for each of two ``k`` variants (one within-k, one where the
first relevant hit sits beyond ``k``).  Scorer / search-view / catalog semantics are untouched.

All data here is fixtures-only; no empirical (measured-on-real-corpus) claim is made.
"""

from __future__ import annotations

import numpy as np

from scripts.embedding_research import similarity
from scripts.embedding_research.common import catalog_analysis as ca

# Fixture-only synthetic corpus (no measured corpus): 5 songs, artists R1 x2 + R2 x3.
# Candidate ordering uses strictly-increasing positive column "strengths" a_i so that, symmetric-sim
# w_i*w_j, every query row ranks candidate songs in the fixed descending order a_4..a_0 (self removed)
# with no ties.  For query a_1 (artist R1, lone R1 peer a_0) the first relevant hit sits beyond any
# k<=3, exercising the full-ranking MRR path.
_FIX_SONGS = ("s0", "s1", "s2", "s3", "s4")
_FIX_ARTISTS = {"s0": "R1", "s1": "R1", "s2": "R2", "s3": "R2", "s4": "R2"}
_FIX_STRENGTH = np.array([1.0, 2.0, 3.0, 4.0, 6.0], dtype=np.float64)


def _fix_sim_matrix() -> np.ndarray:
    return np.outer(_FIX_STRENGTH, _FIX_STRENGTH)  # strictly positive, no ties per row


def _build_catalog_fixture(k: int):
    """Return ``(cfg, per_query, sim, labels)`` for the fixed synthetic corpus at cut-off *k*."""
    sim = _fix_sim_matrix()
    per_query: list[ca.PerQueryResult] = []
    for i, song in enumerate(_FIX_SONGS):
        others = {j: float(sim[i, j]) for j in range(len(_FIX_SONGS)) if j != i}
        per_query.append(
            ca.PerQueryResult(
                query_song_id=song,
                score=max(others.values()),
                winner_counts={},
                candidate_scores={_FIX_SONGS[j]: v for j, v in others.items()},
                candidate_keys=(),
                retained_count=0,
                dropped_count=0,
                variant="fixture",
            )
        )
    cfg = ca.CatalogAnalysisConfig(
        run_id="fixture-lens-align",
        backbone="effnet",
        song_ids=_FIX_SONGS,
        artists=_FIX_ARTISTS,
        k=k,
    )
    return cfg, per_query, sim, [_FIX_ARTISTS[s] for s in _FIX_SONGS]


def _assert_catalog_equals_similarity(k: int, monkeypatch) -> None:
    # The catalog lens mirrors ``similarity``'s *discounted-gain* ``_dcg`` arithmetic (1-based
    # ``log2(rank + 1)`` <-> ``similarity``'s ``log2(r + 2)`` over 0-based ``r``).  When sklearn is
    # installed ``compute_retrieval_metrics`` takes its sklearn NDCG branch instead, which differs for
    # lopsided relevance sets; force the exact ``_dcg`` branch (the line the lens mirrors) for this
    # equivalence check, restoring the module default afterwards.
    monkeypatch.setattr(similarity, "_SKLEARN", False)
    cfg, per_query, sim, labels = _build_catalog_fixture(k)
    cats, _per_song = ca._Lenses(cfg).evaluate(per_query)
    legacy = similarity.compute_retrieval_metrics(sim, labels, k=k)

    checks = [
        ("map_k", "map_k_artist"),
        ("mrr", "mrr"),
        ("ndcg_k", "ndcg_k_artist"),
        ("recall_k", "recall_k_artist"),
    ]
    for cat_key, legacy_key in checks:
        np.testing.assert_allclose(cats[cat_key], legacy[legacy_key], rtol=1e-9, atol=1e-12)
    # MRR over the full ranking: a lone-R1 query s1 whose only peer s0 sits beyond k<=3 still earns 1/4.
    assert cats["mrr"] > 0.0
    assert cats["ndcg_k"] >= 0.0


def test_lens_map_mrr_ndcg_recall_equal_similarity_within_k(monkeypatch) -> None:
    """k covers all relevant hits — verifies NDCG discount and denominators match the authority."""
    _assert_catalog_equals_similarity(k=5, monkeypatch=monkeypatch)


def test_lens_mrr_full_ranking_when_first_relevant_is_beyond_k(monkeypatch) -> None:
    """MRR beyond k: a first same-artist hit past cut-off still counts 1/rank (not 0)."""
    _assert_catalog_equals_similarity(k=2, monkeypatch=monkeypatch)


def test_ndcg_single_top_relevant_is_one_dot_zero() -> None:
    """NDCG for a lone top-ranked relevant song == 1.0 (mirrors similarity's log2(rank+1) discount)."""
    cfg = ca.CatalogAnalysisConfig(
        run_id="fixture-top1",
        backbone="effnet",
        song_ids=("x", "y"),
        artists={"x": "R1", "y": "R1"},
        k=1,
    )
    # x's only candidate y is same-artist and top-ranked => NDCG@1 must be 1.0 (log2(rank+1)=log2(2)=1),
    # not the old 1/log2(rank+2) = 0.6309 discount.
    for top in (1, 9, 8):
        pq = ca.PerQueryResult(
            query_song_id="x",
            score=float(top),
            winner_counts={},
            candidate_scores={"y": float(top)},
            candidate_keys=(),
            retained_count=0,
            dropped_count=0,
            variant="fixture",
        )
        (metrics, _per_song) = ca._Lenses(cfg).evaluate([pq])
        np.testing.assert_allclose(metrics["ndcg_k"], 1.0, rtol=0, atol=1e-12)
        np.testing.assert_allclose(metrics["mrr"], 1.0, rtol=0, atol=1e-12)
