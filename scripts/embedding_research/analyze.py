"""
Phase 3: compute pairwise similarity matrices and retrieval metrics from DuckDB.

For every (backbone, strategy, sim_metric) triple:
  1. Load pooled vectors from DuckDB pooled_vecs table
  2. Build [n_songs, embed_dim] matrix
  3. Compute full pairwise similarity matrix
  4. Evaluate MAP@k, MRR, NDCG@k, Recall@k, disc_score (artist labels)

Head analysis:
  For each (backbone, head, strategy, pathway):
    - Load majority-class labels from DuckDB head_results
    - Compute same-class discrimination
    - Compare PTC vs CTP

ANN sweep:
  Build real HNSW index with faiss on the "mean" strategy pooled vectors.
  Measure recall@k as ef_search varies from 16 to 256.

All results are written back into DuckDB (retrieval_rows, ann_rows, ptc_ctp_rows).

Run from inside the devcontainer:
  python /workspace/scripts/embedding_research/analyze.py [--limit N] [--backbone effnet]
"""

from __future__ import annotations

import argparse
import time

import numpy as np
from tqdm import tqdm

from .config import BACKBONES, HEAD_LABELS, HEADS, bootstrap_nomarr
from .db import (
    connect,
    load_head_labels,
    load_pooled_matrix,
    upsert_ann,
    upsert_ptc_ctp,
    upsert_retrieval,
)
from .pooling import STRATEGIES
from .similarity import (
    METRICS,
    ann_recall_sweep,
    compute_retrieval_metrics,
    cosine_matrix,
)

# ── Artist-label retrieval metrics ─────────────────────────────────────────────


def analyze_strategy(
    con,
    backbone: str,
    strategy: str,
    k: int = 10,
    verbose: bool = False,
) -> None:
    """
    Compute and store retrieval metrics for all sim metrics for one (backbone, strategy).
    """
    vecs, _sids, artists = load_pooled_matrix(con, backbone, strategy)
    if len(vecs) == 0:
        print(f"  [{backbone}/{strategy}] no data -- skipping")
        return

    for metric_name, matrix_fn in METRICS.items():
        t0 = time.time()
        sim_mat = matrix_fn(vecs)
        metrics = compute_retrieval_metrics(sim_mat, artists, k=k)
        upsert_retrieval(con, backbone, strategy, metric_name, k, metrics)
        if verbose:
            print(
                f"  [{backbone}/{strategy}/{metric_name}] "
                f"disc={metrics['disc_score']:.4f} "
                f"map_{k}={metrics[f'map_{k}']:.4f} "
                f"in {time.time() - t0:.1f}s"
            )


# ── Head grouping analysis ─────────────────────────────────────────────────────


def analyze_ptc_vs_ctp(
    con,
    backbone: str,
    strategies: list[str],
    k: int = 10,
    verbose: bool = False,
) -> None:
    """
    For each (head, strategy): compare PTC vs CTP discrimination on the
    cosine sim matrix of that strategy's pooled embeddings.
    Writes results to ptc_ctp_rows.
    """
    for head_name in HEADS.get(backbone, {}):
        label_names = HEAD_LABELS.get(head_name, ["class_0", "class_1"])

        for strategy in strategies:
            vecs, sids, _ = load_pooled_matrix(con, backbone, strategy)
            if len(vecs) == 0:
                continue
            cos_mat = cosine_matrix(vecs)

            row: dict = {}
            for pathway in ("ptc", "ctp"):
                labels = load_head_labels(con, sids, backbone, head_name, strategy, pathway, label_names)
                if labels is None:
                    continue
                mask_idx = [i for i, l in enumerate(labels) if l != "unknown"]
                if len(mask_idx) < 10:
                    continue
                sub_sim = cos_mat[np.ix_(mask_idx, mask_idx)]
                sub_labels = [labels[i] for i in mask_idx]
                m = compute_retrieval_metrics(sub_sim, sub_labels, k=k)
                row[f"{pathway}_disc"] = m["disc_score"]
                row[f"{pathway}_map"] = m[f"map_{k}"]

            if "ptc_disc" in row and "ctp_disc" in row:
                row["delta_disc"] = row["ptc_disc"] - row["ctp_disc"]
                row["delta_map"] = row["ptc_map"] - row["ctp_map"]
                upsert_ptc_ctp(con, backbone, head_name, strategy, row)
                if verbose:
                    print(
                        f"  [{backbone}/{head_name}/{strategy}] "
                        f"ptc_disc={row['ptc_disc']:.4f} ctp_disc={row['ctp_disc']:.4f} "
                        f"delta={row['delta_disc']:+.4f}"
                    )


# ── ANN recall sweep ───────────────────────────────────────────────────────────


def analyze_ann(
    con,
    backbone: str,
    strategy: str = "mean",
    k: int = 10,
    n_queries: int = 200,
    verbose: bool = False,
) -> None:
    """
    Build HNSW index on cosine space and measure recall@k at various ef_search values.
    Writes results to ann_rows.
    """
    vecs, _sids, artists = load_pooled_matrix(con, backbone, strategy)
    if len(vecs) == 0:
        return

    sweep = ann_recall_sweep(vecs, artists, k=k, n_queries=n_queries)
    for row in sweep.values():
        upsert_ann(con, backbone, strategy, row["ef_search"], row["recall_k"], row["backend"])
        if verbose:
            print(f"  [{backbone}/ann] ef={row['ef_search']:3d} recall@{k}={row['recall_k']:.4f} ({row['backend']})")


# ── Entry point ────────────────────────────────────────────────────────────────


def run(
    limit: int | None = None,
    k: int = 10,
    ann_n_queries: int = 200,
    backbones: list[str] | None = None,
    strategies: list[str] | None = None,
    verbose: bool = False,
) -> None:
    bootstrap_nomarr()

    bb_names = backbones or list(BACKBONES)
    strat_names = strategies or list(STRATEGIES)

    with connect() as con:
        for bb_name in bb_names:
            print(f"\n=== {bb_name} ===")

            # ── Embedding retrieval metrics ────────────────────────────────────
            for strategy in tqdm(strat_names, desc=f"[{bb_name}] strategies"):
                analyze_strategy(con, bb_name, strategy, k=k, verbose=verbose)

            # ── PTC vs CTP ────────────────────────────────────────────────────
            if HEADS.get(bb_name):
                print(f"[{bb_name}] Analyzing PTC vs CTP ...")
                analyze_ptc_vs_ctp(con, bb_name, strat_names, k=k, verbose=verbose)

            # ── ANN sweep (cosine HNSW) on mean strategy ──────────────────────
            print(f"[{bb_name}] Running ANN recall sweep ...")
            analyze_ann(con, bb_name, strategy="mean", k=k, n_queries=ann_n_queries, verbose=verbose)

    print("\nAnalysis complete. Results stored in DuckDB.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 3: similarity analysis from DuckDB")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--k", type=int, default=10, help="Retrieval cutoff k")
    ap.add_argument("--ann-queries", type=int, default=200)
    ap.add_argument("--backbone", nargs="+", choices=list(BACKBONES), default=None)
    ap.add_argument("--strategy", nargs="+", choices=list(STRATEGIES), default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    run(
        limit=args.limit,
        k=args.k,
        ann_n_queries=args.ann_queries,
        backbones=args.backbone,
        strategies=args.strategy,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
