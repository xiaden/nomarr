"""Filesystem cache for aggregated pairwise similarity matrices.

Each ``(backbone, bin_mode, std_thresh, rep_a, rep_b, metric)`` result is
stored as a single compressed .npz file:

    {SIM_CACHE_BASE}/{backbone}/{bin_mode}/{std_thresh:.3f}/{rep_a}_{rep_b}_{metric}.npz

npz contents
------------
song_ids            [n]      str dtype   — song IDs in matrix row/column order
sim_{agg}           [n, n]   float32     — pairwise similarity per agg method

Retrieval metrics (MAP@K, precision@K, etc.) are **not** stored here.
They are always re-derived from these matrices in milliseconds since they
require a global re-rank over all songs.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ..config import OUTPUT_ROOT as _OUTPUT_ROOT

_log = logging.getLogger(__name__)

SIM_CACHE_BASE: Path = _OUTPUT_ROOT / "sim_cache"

_AGG_METHODS: tuple[str, ...] = ("mean", "median", "max", "min")


def sim_cache_path(
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    rep_a: str,
    rep_b: str,
    metric: str,
) -> Path:
    """Return the .npz path for a given similarity config."""
    fname = f"{rep_a}_{rep_b}_{metric}.npz"
    return SIM_CACHE_BASE / backbone / bin_mode / f"{std_thresh:.3f}" / fname


def load_sim(
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    rep_a: str,
    rep_b: str,
    metric: str,
) -> tuple[list[str], dict[str, np.ndarray]] | None:
    """Load cached similarity matrices.

    Returns ``(sids, mats)`` where ``mats`` maps each agg method name to an
    ``[n, n] float32`` matrix, or ``None`` if no cache file exists or is
    unreadable.

    The caller should compare ``sids`` against the current song list; if they
    differ the cache is stale and a full recompute is needed.
    """
    p = sim_cache_path(backbone, bin_mode, std_thresh, rep_a, rep_b, metric)
    if not p.exists():
        return None
    try:
        data = np.load(str(p), allow_pickle=False)
        sids: list[str] = data["song_ids"].tolist()
        mats: dict[str, np.ndarray] = {
            agg: data[f"sim_{agg}"]
            for agg in _AGG_METHODS
            if f"sim_{agg}" in data.files
        }
        if not mats:
            _log.warning(
                "sim_cache: empty mats in %s/%s/%.3f %s_%s_%s",
                backbone, bin_mode, std_thresh, rep_a, rep_b, metric,
            )
            return None
        return sids, mats
    except Exception as exc:
        _log.warning(
            "sim_cache.load failed (%s/%s/%.3f/%s_%s_%s): %s",
            backbone, bin_mode, std_thresh, rep_a, rep_b, metric, exc,
        )
        return None


def save_sim(
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    rep_a: str,
    rep_b: str,
    metric: str,
    sids: list[str],
    mats: dict[str, np.ndarray],
) -> None:
    """Save aggregated similarity matrices to a compressed .npz file."""
    p = sim_cache_path(backbone, bin_mode, std_thresh, rep_a, rep_b, metric)
    p.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {
        "song_ids": np.array(sids),
        **{f"sim_{agg}": mat.astype(np.float32) for agg, mat in mats.items()},
    }
    np.savez_compressed(str(p), **arrays)
    _log.debug(
        "sim_cache.save  %s/%s/%.3f  %s_%s_%s  n=%d",
        backbone, bin_mode, std_thresh, rep_a, rep_b, metric, len(sids),
    )
