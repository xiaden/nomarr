"""Filesystem cache for binned embeddings (vecs + head activations).

Each ``(backbone, bin_mode, std_thresh, song_id)`` combination is stored as a
single ``.npz`` file:

    {CACHE_BASE}/{backbone}/{bin_mode}/{std_thresh:.3f}/{song_id}.npz

npz contents
------------
pool_{strategy}_raw   [n_bins, D] float32   — unnormalised bin pooled vector
pool_{strategy}_norm  [n_bins, D] float32   — L2-normalised bin pooled vector
weights               [n_bins]    int32      — patch count per bin
outliers              [n_bins]    int32      — outlier count per bin
head_{name}           [n_bins, C] float32   — head activation per bin

The DB is no longer used for binned vec / head data; it only stores scalar
analysis results and song metadata.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ..config import OUTPUT_ROOT as _OUTPUT_ROOT

_log = logging.getLogger(__name__)

CACHE_BASE: Path = _OUTPUT_ROOT / "binned_cache"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def cache_path(backbone: str, bin_mode: str, std_thresh: float, song_id: str) -> Path:
    return CACHE_BASE / backbone / bin_mode / f"{std_thresh:.3f}" / f"{song_id}.npz"


def config_dir(backbone: str, bin_mode: str, std_thresh: float) -> Path:
    return CACHE_BASE / backbone / bin_mode / f"{std_thresh:.3f}"


# ---------------------------------------------------------------------------
# Completion checks
# ---------------------------------------------------------------------------

def song_done(backbone: str, bin_mode: str, std_thresh: float, song_id: str) -> bool:
    return cache_path(backbone, bin_mode, std_thresh, song_id).exists()


def list_done_keys() -> set[tuple[str, str, str, float]]:
    """Return ``(song_id, backbone, bin_mode, std_thresh)`` for every cached file."""
    if not CACHE_BASE.exists():
        return set()
    out: set[tuple[str, str, str, float]] = set()
    for bb_dir in CACHE_BASE.iterdir():
        if not bb_dir.is_dir():
            continue
        for bm_dir in bb_dir.iterdir():
            if not bm_dir.is_dir():
                continue
            for th_dir in bm_dir.iterdir():
                if not th_dir.is_dir():
                    continue
                try:
                    th = float(th_dir.name)
                except ValueError:
                    continue
                for f in th_dir.glob("*.npz"):
                    out.add((f.stem, bb_dir.name, bm_dir.name, th))
    return out


def list_configs(backbone: str | None = None) -> set[tuple[str, str, float]]:
    """Return ``(backbone, bin_mode, std_thresh)`` for every non-empty config directory."""
    if not CACHE_BASE.exists():
        return set()
    out: set[tuple[str, str, float]] = set()
    bb_dirs = [CACHE_BASE / backbone] if backbone else [
        d for d in CACHE_BASE.iterdir() if d.is_dir()
    ]
    for bb_dir in bb_dirs:
        if not bb_dir.is_dir():
            continue
        for bm_dir in bb_dir.iterdir():
            if not bm_dir.is_dir():
                continue
            for th_dir in bm_dir.iterdir():
                if not th_dir.is_dir():
                    continue
                try:
                    th = float(th_dir.name)
                except ValueError:
                    continue
                if any(th_dir.glob("*.npz")):
                    out.add((bb_dir.name, bm_dir.name, th))
    return out


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def save(
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
    bulk_vecs: list[tuple],
    bulk_heads: list[tuple],
) -> None:
    """Write one song's binned data to an npz file.

    Parameters
    ----------
    bulk_vecs:
        Rows with schema
        ``(sid, backbone, bin_mode, std_thresh, bin_id, pool_strategy,
           vec_raw_bytes, vec_norm_bytes, weight, outlier_count)``
    bulk_heads:
        Rows with schema
        ``(sid, backbone, head_name, bin_mode, std_thresh, bin_id,
           act_bytes, seg_size)``
    """
    if not bulk_vecs and not bulk_heads:
        return

    # --- collect per-bin, per-pool-strategy vecs ---
    bins: dict[int, dict] = {}
    for row in bulk_vecs:
        _, _, _, _, bin_id, pool_strategy, raw_b, norm_b, weight, outlier_count = row
        if bin_id not in bins:
            bins[bin_id] = {"weight": weight, "outlier_count": outlier_count, "pools": {}, "heads": {}}
        bins[bin_id]["pools"][pool_strategy] = {
            "raw": np.frombuffer(raw_b, dtype=np.float32).copy(),
            "norm": np.frombuffer(norm_b, dtype=np.float32).copy(),
        }

    # --- collect per-bin head activations ---
    for row in bulk_heads:
        _, _, head_name, _, _, bin_id, act_b, _ = row
        if bin_id not in bins:
            bins[bin_id] = {"weight": 0, "outlier_count": 0, "pools": {}, "heads": {}}
        bins[bin_id]["heads"][head_name] = np.frombuffer(act_b, dtype=np.float32).copy()

    if not bins:
        return

    sorted_ids = sorted(bins.keys())
    first = bins[sorted_ids[0]]
    strategies = sorted(first["pools"])
    heads = sorted(first["heads"])

    arrays: dict[str, np.ndarray] = {
        "weights": np.array([bins[i]["weight"] for i in sorted_ids], dtype=np.int32),
        "outliers": np.array([bins[i].get("outlier_count", 0) for i in sorted_ids], dtype=np.int32),
    }

    if strategies:
        vec_d = next(iter(first["pools"].values()))["raw"].shape[0]
        zeros_vec = np.zeros(vec_d, dtype=np.float32)
        for st in strategies:
            arrays[f"pool_{st}_raw"] = np.stack([
                bins[i]["pools"].get(st, {"raw": zeros_vec})["raw"] for i in sorted_ids
            ])
            arrays[f"pool_{st}_norm"] = np.stack([
                bins[i]["pools"].get(st, {"norm": zeros_vec})["norm"] for i in sorted_ids
            ])

    for h in heads:
        n_classes = first["heads"][h].shape[0]
        zeros_act = np.zeros(n_classes, dtype=np.float32)
        arrays[f"head_{h}"] = np.stack([
            bins[i]["heads"].get(h, zeros_act) for i in sorted_ids
        ])

    p = cache_path(backbone, bin_mode, std_thresh, song_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez(str(p), **arrays)
    _log.debug(
        "cache.save  %s/%s/%.3f/%s  bins=%d strats=%d heads=%d",
        backbone, bin_mode, std_thresh, song_id,
        len(sorted_ids), len(strategies), len(heads),
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def load_bins(
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
    *,
    vec_type: str = "raw",
) -> list[dict]:
    """Load bin dicts for one song.

    Returns a list (one entry per bin) with keys:
    ``bin_id``, ``weight``, ``outlier_count``, ``vec_{strategy}`` for each
    pool strategy present in the file.

    Parameters
    ----------
    vec_type:
        ``"raw"`` (default) loads unnormalised vectors; ``"norm"`` loads L2-normalised ones.
    """
    p = cache_path(backbone, bin_mode, std_thresh, song_id)
    data = np.load(str(p))
    suffix = "_raw" if vec_type == "raw" else "_norm"
    try:
        n_bins = int(data["weights"].shape[0])
        strategies = sorted(
            k[5 : -len(suffix)]
            for k in data.files
            if k.startswith("pool_") and k.endswith(suffix)
        )
        out: list[dict] = []
        for i in range(n_bins):
            b: dict = {
                "bin_id": i,
                "weight": int(data["weights"][i]),
                "outlier_count": int(data["outliers"][i]),
            }
            for st in strategies:
                b[f"vec_{st}"] = data[f"pool_{st}{suffix}"][i]
            out.append(b)
    finally:
        data.close()
    return out


def list_sids_for_config(backbone: str, bin_mode: str, std_thresh: float) -> set[str]:
    """Return the set of song_ids cached for a specific config."""
    d = config_dir(backbone, bin_mode, std_thresh)
    if not d.exists():
        return set()
    return {f.stem for f in d.glob("*.npz")}



def load_bin_stats(
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
) -> list[dict]:
    """Load only weights, outlier counts, and mean vec per bin.

    Lightweight alternative to ``load_bins`` for computing song-level stats
    (``_compute_song_stats``) without loading all four pool-strategy arrays.
    Each returned dict has keys: ``bin_id``, ``weight``, ``outlier_count``,
    and ``vec_mean`` (when a 'mean' strategy is present in the cache).
    """
    p = cache_path(backbone, bin_mode, std_thresh, song_id)
    data = np.load(str(p))
    try:
        n_bins = int(data["weights"].shape[0])
        out: list[dict] = []
        for i in range(n_bins):
            b: dict = {
                "bin_id": i,
                "weight": int(data["weights"][i]),
                "outlier_count": int(data["outliers"][i]),
            }
            mean_key = "pool_mean_raw"
            if mean_key in data.files:
                b["vec_mean"] = data[mean_key][i].copy()
            out.append(b)
    finally:
        data.close()
    return out


def load_norm_pair(
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
    rep_a: str,
    rep_b: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Load L2-normalised vectors for exactly two pool strategies.

    Returns ``(norm_a [n_bins, D], norm_b [n_bins, D])`` float32 arrays.
    When ``rep_a == rep_b`` both outputs share the same array (no extra copy).
    Opens the .npz file once and closes it immediately.
    """
    p = cache_path(backbone, bin_mode, std_thresh, song_id)
    data = np.load(str(p))
    try:
        norm_a = data[f"pool_{rep_a}_norm"].copy()
        norm_b = data[f"pool_{rep_b}_norm"].copy() if rep_b != rep_a else norm_a
    finally:
        data.close()
    return norm_a, norm_b