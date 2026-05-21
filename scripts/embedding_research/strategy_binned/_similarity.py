"""Similarity helpers: _sim_matrix, _aggregate, pair/combo aggregation."""

from __future__ import annotations

import numpy as _np

from ..similarity import l2_normalise as _l2_normalise
from ._constants import AGG_METHODS, REP_TYPES, SIM_METRICS


def _sim_key(rep_a: str, rep_b: str, metric: str, agg: str) -> str:
    return f"{rep_a}__{rep_b}__{metric}__{agg}"


def _parse_key(key: str) -> tuple[str, str, str, str]:
    rep_a, rep_b, metric, agg = key.split("__")
    return rep_a, rep_b, metric, agg


def _sim_matrix(va: _np.ndarray, vb: _np.ndarray, metric: str) -> _np.ndarray:
    if metric == "cosine":
        a = _np.asarray(_l2_normalise(va), dtype=_np.float32)
        b = _np.asarray(_l2_normalise(vb), dtype=_np.float32)
        return _np.asarray(a @ b.T, dtype=_np.float32)
    if metric == "l2":
        sq_a = (va**2).sum(axis=1, keepdims=True)
        sq_b = (vb**2).sum(axis=1, keepdims=True)
        sq_dist = _np.maximum(sq_a + sq_b.T - 2.0 * (va @ vb.T), 0.0)
        return _np.asarray(1.0 / (1.0 + _np.sqrt(sq_dist)), dtype=_np.float32)
    raise ValueError(f"Unknown metric: {metric!r}")


def _aggregate(mat: _np.ndarray, agg: str) -> float:
    if agg == "mean":
        return float(mat.mean())
    if agg == "median":
        return float(_np.median(mat))
    if agg == "max":
        return float(mat.max())
    if agg == "min":
        return float(mat.min())
    raise ValueError(f"Unknown agg: {agg!r}")


def _compute_pair_sims(bins_a: list[dict], bins_b: list[dict]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for metric in SIM_METRICS:
        for rep_a in REP_TYPES:
            va = _np.stack([b[f"vec_{rep_a}"] for b in bins_a]).astype(_np.float32)
            for rep_b in REP_TYPES:
                vb = _np.stack([b[f"vec_{rep_b}"] for b in bins_b]).astype(_np.float32)
                mat = _sim_matrix(va, vb, metric)
                for agg in AGG_METHODS:
                    scores[_sim_key(rep_a, rep_b, metric, agg)] = _aggregate(mat, agg)
    return scores


def _build_combo_sim_matrix(
    song_data: list[list[dict]],
    rep_a: str,
    rep_b: str,
    metric: str,
    agg: str,
) -> _np.ndarray:
    n = len(song_data)
    mat = _np.zeros((n, n), dtype=_np.float32)
    for i in range(n):
        va = _np.stack([b[f"vec_{rep_a}"] for b in song_data[i]]).astype(_np.float32)
        for j in range(i, n):
            vb = _np.stack([b[f"vec_{rep_b}"] for b in song_data[j]]).astype(_np.float32)
            sim = _sim_matrix(va, vb, metric)
            val = _aggregate(sim, agg)
            mat[i, j] = val
            mat[j, i] = val
    _np.fill_diagonal(mat, 1.0)
    return mat
