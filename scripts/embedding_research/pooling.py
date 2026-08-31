"""
Pooling strategies: [n_patches, d] → [d].
All functions return float32 numpy arrays.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Mapping

_FLAT_STRATEGY_KEY = "flat_strategies"


def load_flat_strategy_names(cfg: Mapping[str, Any]) -> list[str]:
    """Return the explicit configured flat strategy list.

    Reads ``[pooling] flat_strategies`` from the research config mapping.  When
    an explicit list is present it is a benchmark-baseline configuration and
    MUST include the ``medoid`` strategy (the observed-patch baseline); each
    name is validated against the known flat pooling strategies.  When no
    explicit list is present, every known flat strategy (including ``medoid``)
    is returned.  The result preserves configuration order and is deduplicated.
    """
    pooling_cfg = (cfg or {}).get("pooling") or {}
    explicit = pooling_cfg.get(_FLAT_STRATEGY_KEY)
    if explicit is None:
        return list(STRATEGIES)

    names = [str(name) for name in explicit]
    if not names:
        raise ValueError("flat_strategies must not be empty when explicitly configured")

    unknown = sorted(name for name in names if name not in STRATEGIES)
    if unknown:
        raise ValueError(f"Unknown flat strategy name(s): {unknown}. Known: {sorted(STRATEGIES)}")
    if "medoid" not in names:
        raise ValueError(f"flat_strategies is a benchmark baseline and must include 'medoid'; got {names}")

    seen: set[str] = set()
    ordered = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


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


def select_global_medoid_index(unit_patches: np.ndarray) -> tuple[int, float]:
    """Return ``(local_index, centrality)`` of the observed global medoid.

    *unit_patches* is the raw ``[n_patches, d]`` patch matrix (it is unit
    normalized here, despite the parameter name): each row is L2-normalized
    for cosine centrality, then the observed row with the maximum *mean cosine
    centrality* to the other rows is chosen.  Ties resolve to the smallest
    index (``np.argmax`` first-max semantics).  Zero-norm rows normalize to
    the zero vector and contribute zero similarity; a zero-norm row is never
    selected while any nonzero row exists, and an all-zero patch set selects
    index ``0`` deterministically.  A single-patch input returns ``(0, 0.0)``.
    """
    unit_patches = np.asarray(unit_patches)
    if unit_patches.ndim != 2:
        raise ValueError(f"Expected a 2D patch matrix, got shape {unit_patches.shape}")
    n = unit_patches.shape[0]
    if n == 0:
        raise ValueError("Cannot select a medoid from an empty patch set")

    norms = np.linalg.norm(unit_patches, axis=1)
    unit = np.zeros_like(unit_patches, dtype=np.float32)
    np.divide(unit_patches, norms[:, None], out=unit, where=(norms[:, None] != 0))
    sim = unit @ unit.T  # [n, n] cosine similarity

    if n == 1:
        return 0, 0.0

    off_diag = sim * ~np.eye(n, dtype=bool)
    centrality = off_diag.sum(axis=1) / (n - 1)

    has_norm = norms != 0
    if has_norm.any():
        candidates = np.flatnonzero(has_norm)
        idx = int(candidates[np.argmax(centrality[candidates])])
    else:
        idx = 0
    return idx, float(centrality[idx])


def pool_medoid(emb: np.ndarray) -> np.ndarray:
    """Choose the observed raw patch with maximum mean cosine centrality.

    Returns the observed float32 patch (never a synthetic centroid).  This is
    the flat-strategy medoid, distinct from the forbidden aggregation-level
    ``agg_method=medoid``.
    """
    idx, _ = select_global_medoid_index(emb)
    return emb[idx].astype(np.float32)


# Registry ordered for consistent reporting.
STRATEGIES: dict[str, object] = {
    "mean": pool_mean,
    "trimmed_10": lambda e: pool_trimmed_mean(e, 0.10),
    "trimmed_20": lambda e: pool_trimmed_mean(e, 0.20),
    "median": pool_median,
    "max_norm": pool_max_norm,
    "l2norm_mean": pool_l2norm_mean,
    "medoid": pool_medoid,
}
