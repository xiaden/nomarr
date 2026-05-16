"""
Pooling strategies: [n_patches, d] → [d].
All functions return float32 numpy arrays.
"""

from __future__ import annotations

import numpy as np


def pool_mean(emb: np.ndarray) -> np.ndarray:
    return emb.mean(axis=0)


def pool_trimmed_mean(emb: np.ndarray, trim_frac: float = 0.10) -> np.ndarray:
    """Drop top/bottom trim_frac patches by L2 norm, then mean the rest."""
    n = len(emb)
    k = int(n * trim_frac)
    if k == 0 or 2 * k >= n:
        return emb.mean(axis=0)
    norms = np.linalg.norm(emb, axis=1)
    keep = np.argsort(norms)[k : n - k]
    return emb[keep].mean(axis=0)


def pool_median(emb: np.ndarray) -> np.ndarray:
    return np.median(emb, axis=0).astype(np.float32)


def pool_max_norm(emb: np.ndarray) -> np.ndarray:
    """Single patch with highest L2 norm."""
    return emb[np.argmax(np.linalg.norm(emb, axis=1))]


def pool_l2norm_mean(emb: np.ndarray) -> np.ndarray:
    """L2-normalize each patch to the unit sphere, then mean."""
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (emb / norms).mean(axis=0).astype(np.float32)


# Registry ordered for consistent reporting.
STRATEGIES: dict[str, object] = {
    "mean": pool_mean,
    "trimmed_10": lambda e: pool_trimmed_mean(e, 0.10),
    "trimmed_20": lambda e: pool_trimmed_mean(e, 0.20),
    "median": pool_median,
    "max_norm": pool_max_norm,
    "l2norm_mean": pool_l2norm_mean,
}
