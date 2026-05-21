"""Calibration helpers: _calibrate and _load_cached_calibration."""

from __future__ import annotations

from pathlib import Path as _Path
from typing import Any as _Any
from typing import cast as _cast

import numpy as _np

from .. import db as _db
from ..config import patches_path as _patches_path
from ..config import song_id as _song_id
from ..helpers.binning import BIN_MODES, DIST_FNS as _DIST_FNS
from ..similarity import l2_normalise as _l2_normalise


def _load_cached_calibration(con, backbone: str) -> dict[str, dict] | None:
    """Return per-bin-mode calibration stats dict, or None if unavailable."""
    load_calibration = _cast("_Any", _db.load_calibration)
    try:
        cached = load_calibration(con, backbone)
    except TypeError:
        cached = None
    if isinstance(cached, dict) and cached and "p50" not in cached:
        return cached

    per_mode: dict[str, dict] = {}
    for bin_mode in BIN_MODES:
        try:
            row = load_calibration(con, backbone, bin_mode)
        except TypeError:
            row = None
        if row is not None:
            per_mode[bin_mode] = row
    return per_mode or None


def _calibrate(
    con,
    backbone: str,
    audio_paths: list[_Path],
    force: bool = False,
) -> dict[str, dict]:
    """Compute per-dist-mode calibration stats and persist to DuckDB."""
    results: dict[str, dict] = {}
    load_calibration = _cast("_Any", _db.load_calibration)
    for dist_mode, dist_fn in _DIST_FNS.items():
        if not force:
            cached = load_calibration(con, backbone, dist_mode)
            if cached is not None:
                results[dist_mode] = cached
                continue
        dists: list[float] = []
        for path in audio_paths:
            song_sidecar = _patches_path(_song_id(path), backbone)
            if not song_sidecar.exists():
                continue
            raw = _np.load(str(song_sidecar), mmap_mode="r")
            if len(raw) < 2:
                continue
            norm = _l2_normalise(raw.astype(_np.float32))
            centroid = norm.mean(axis=0)
            dists.extend(dist_fn(patch, centroid) for patch in norm)
        if not dists:
            continue
        arr = _np.array(dists, dtype=_np.float64)
        stats = {
            "p10": float(_np.percentile(arr, 10)),
            "p25": float(_np.percentile(arr, 25)),
            "p50": float(_np.percentile(arr, 50)),
            "p75": float(_np.percentile(arr, 75)),
            "mean_d": float(arr.mean()),
            "sigma_d": float(arr.std()),
            "n_patches": len(dists),
        }
        _db.upsert_calibration(
            con,
            backbone,
            dist_mode,
            stats["p10"],
            stats["p25"],
            stats["p50"],
            stats["p75"],
            stats["mean_d"],
            stats["sigma_d"],
            int(stats["n_patches"]),
        )
        results[dist_mode] = stats
    return results
