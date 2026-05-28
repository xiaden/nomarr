"""Filesystem cache for PTC-derived binned embeddings (vecs + head activations).

Each ``(backbone, bin_mode, std_thresh, song_id)`` combination is stored as a
single ``.npz`` file:

    {CACHE_BASE}/{backbone}/{bin_mode}/{std_thresh:.3f}/{song_id}.npz

npz contents
------------
pool_{strategy}_raw   [n_bins, D] float32   — unnormalised bin pooled vector
pool_{strategy}_norm  [n_bins, D] float32   — L2-normalised bin pooled vector
weights               [n_bins]    int32      — patch count per bin
outliers              [n_bins]    int32      — outlier count per bin
bin_start_idx         [n_bins]    int32      — first patch index in each bin
bin_end_idx           [n_bins]    int32      — last patch index in each bin
pool_{strategy}_selected_global_idx [n_bins] int32 — selected source patch idx (medoid)
pool_{strategy}_selected_local_idx  [n_bins] int32 — selected local idx in bin (medoid)
pool_{strategy}_centrality          [n_bins] float32 — mean cosine centrality (medoid)
head_{name}           [n_bins, C] float32   — head activation per bin

The DB is no longer used for binned vec / head data; it only stores scalar
analysis results and song metadata.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from scripts.embedding_research.config import OUTPUT_ROOT as _OUTPUT_ROOT
from scripts.embedding_research.helpers.binning import cache_semantics_tag as _cache_semantics_tag
from scripts.embedding_research.helpers.binning import threshold_key as _threshold_key
from scripts.embedding_research.helpers.cache_utils import missing_sids as _missing_sids
from scripts.embedding_research.vector_types import UnitTensor

_log = logging.getLogger(__name__)

CACHE_BASE: Path = _OUTPUT_ROOT / "cache" / "binned_ptc" / _cache_semantics_tag()


def _purge_corrupt(p: Path) -> None:
    """Delete a corrupt cache file and warn. Next run will recompute it."""
    try:
        p.unlink()
        _log.warning("Deleted corrupt cache file (will recompute): %s", p)
    except OSError as e:
        _log.warning("Could not delete corrupt cache file %s: %s", p, e)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def cache_path(backbone: str, bin_mode: str, std_thresh: float, song_id: str) -> Path:
    return CACHE_BASE / backbone / bin_mode / _threshold_key(std_thresh) / f"{song_id}.npz"


def config_dir(backbone: str, bin_mode: str, std_thresh: float) -> Path:
    return CACHE_BASE / backbone / bin_mode / _threshold_key(std_thresh)


# ---------------------------------------------------------------------------
# Completion checks
# ---------------------------------------------------------------------------


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
    bb_dirs = [CACHE_BASE / backbone] if backbone else [d for d in CACHE_BASE.iterdir() if d.is_dir()]
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


def list_sids(backbone: str, bin_mode: str, std_thresh: float) -> list[str]:
    """Return song_ids present in the filesystem cache for a given config. Zero-length files are purged."""
    d = config_dir(backbone, bin_mode, std_thresh)
    if not d.exists():
        return []
    valid = []
    for f in d.glob("*.npz"):
        if f.stat().st_size == 0:
            _purge_corrupt(f)
        else:
            valid.append(f.stem)
    return sorted(valid)


def missing_for_config(song_ids: list[str], backbone: str, bin_mode: str, std_thresh: float) -> list[str]:
    """Return song_ids not yet cached for this (backbone, bin_mode, std_thresh). Zero-length files are purged."""
    return _missing_sids(song_ids, config_dir(backbone, bin_mode, std_thresh), suffix=".npz")


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
           vec_raw_bytes, vec_norm_bytes, weight, outlier_count,
           selected_global_idx, selected_local_idx, medoid_centrality,
           bin_start_idx, bin_end_idx)``
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
        _, _, _, _, bin_id, pool_strategy, raw_b, norm_b, weight, outlier_count, *meta = row
        selected_global_idx = int(meta[0]) if len(meta) >= 1 else -1
        selected_local_idx = int(meta[1]) if len(meta) >= 2 else -1
        centrality = float(meta[2]) if len(meta) >= 3 else float("nan")
        bin_start_idx = int(meta[3]) if len(meta) >= 4 else -1
        bin_end_idx = int(meta[4]) if len(meta) >= 5 else -1
        if bin_id not in bins:
            bins[bin_id] = {
                "weight": weight,
                "outlier_count": outlier_count,
                "bin_start_idx": bin_start_idx,
                "bin_end_idx": bin_end_idx,
                "pools": {},
                "heads": {},
            }
        bins[bin_id]["pools"][pool_strategy] = {
            "raw": np.frombuffer(raw_b, dtype=np.float32).copy(),
            "norm": np.frombuffer(norm_b, dtype=np.float32).copy(),
            "selected_global_idx": selected_global_idx,
            "selected_local_idx": selected_local_idx,
            "centrality": centrality,
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
        "bin_start_idx": np.array([bins[i].get("bin_start_idx", -1) for i in sorted_ids], dtype=np.int32),
        "bin_end_idx": np.array([bins[i].get("bin_end_idx", -1) for i in sorted_ids], dtype=np.int32),
    }

    if strategies:
        vec_d = next(iter(first["pools"].values()))["raw"].shape[0]
        zeros_vec = np.zeros(vec_d, dtype=np.float32)
        for st in strategies:
            arrays[f"pool_{st}_raw"] = np.stack(
                [bins[i]["pools"].get(st, {"raw": zeros_vec})["raw"] for i in sorted_ids]
            )
            arrays[f"pool_{st}_norm"] = np.stack(
                [bins[i]["pools"].get(st, {"norm": zeros_vec})["norm"] for i in sorted_ids]
            )
            arrays[f"pool_{st}_selected_global_idx"] = np.array(
                [bins[i]["pools"].get(st, {}).get("selected_global_idx", -1) for i in sorted_ids],
                dtype=np.int32,
            )
            arrays[f"pool_{st}_selected_local_idx"] = np.array(
                [bins[i]["pools"].get(st, {}).get("selected_local_idx", -1) for i in sorted_ids],
                dtype=np.int32,
            )
            arrays[f"pool_{st}_centrality"] = np.array(
                [bins[i]["pools"].get(st, {}).get("centrality", np.nan) for i in sorted_ids],
                dtype=np.float32,
            )

    for h in heads:
        n_classes = first["heads"][h].shape[0]
        zeros_act = np.zeros(n_classes, dtype=np.float32)
        arrays[f"head_{h}"] = np.stack([bins[i]["heads"].get(h, zeros_act) for i in sorted_ids])

    p = cache_path(backbone, bin_mode, std_thresh, song_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez(str(p), **arrays)
    _log.info(
        "cache.save  %s/%s/%.3f/%s  bins=%d strats=%d heads=%d",
        backbone,
        bin_mode,
        std_thresh,
        song_id,
        len(sorted_ids),
        len(strategies),
        len(heads),
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
    try:
        data = np.load(str(p))
    except (EOFError, OSError, ValueError):
        _purge_corrupt(p)
        return []
    suffix = "_raw" if vec_type == "raw" else "_norm"
    try:
        n_bins = int(data["weights"].shape[0])
        strategies = sorted(k[5 : -len(suffix)] for k in data.files if k.startswith("pool_") and k.endswith(suffix))
        out: list[dict] = []
        for i in range(n_bins):
            b: dict = {
                "bin_id": i,
                "weight": int(data["weights"][i]),
                "outlier_count": int(data["outliers"][i]),
                "bin_start_idx": int(data["bin_start_idx"][i]) if "bin_start_idx" in data.files else -1,
                "bin_end_idx": int(data["bin_end_idx"][i]) if "bin_end_idx" in data.files else -1,
            }
            for st in strategies:
                b[f"vec_{st}"] = data[f"pool_{st}{suffix}"][i]
                g_key = f"pool_{st}_selected_global_idx"
                l_key = f"pool_{st}_selected_local_idx"
                c_key = f"pool_{st}_centrality"
                if g_key in data.files:
                    g_idx = int(data[g_key][i])
                    b[f"{st}_selected_global_idx"] = None if g_idx < 0 else g_idx
                if l_key in data.files:
                    l_idx = int(data[l_key][i])
                    b[f"{st}_selected_local_idx"] = None if l_idx < 0 else l_idx
                if c_key in data.files:
                    c_val = float(data[c_key][i])
                    b[f"{st}_centrality"] = None if np.isnan(c_val) else c_val
            out.append(b)
    finally:
        data.close()
    return out


def load_bin_stats(
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
) -> list[dict]:
    """Load only weights, outlier counts, and one representative vec per bin.

    Lightweight alternative to ``load_bins`` for computing song-level stats
    (``_compute_song_stats``) without loading all four pool-strategy arrays.
    Each returned dict has keys: ``bin_id``, ``weight``, ``outlier_count``,
    and ``vec_mean`` (legacy key, sourced from ``mean`` if present, otherwise
    from ``median``/``medoid``/first available strategy).
    """
    p = cache_path(backbone, bin_mode, std_thresh, song_id)
    try:
        data = np.load(str(p))
    except (EOFError, OSError, ValueError):
        _purge_corrupt(p)
        return []
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
            else:
                fallback_key: str | None = None
                for candidate in ("pool_median_raw", "pool_medoid_raw"):
                    if candidate in data.files:
                        fallback_key = candidate
                        break
                if fallback_key is None:
                    raw_keys = sorted(k for k in data.files if k.startswith("pool_") and k.endswith("_raw"))
                    fallback_key = raw_keys[0] if raw_keys else None
                if fallback_key is not None:
                    b["vec_mean"] = data[fallback_key][i].copy()
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
) -> tuple[UnitTensor, UnitTensor]:
    """Load L2-normalised vectors for exactly two pool strategies.

    Returns ``(norm_a [n_bins, D], norm_b [n_bins, D])`` UnitTensor wrapping
    float32 row-normalised arrays.
    When ``rep_a == rep_b`` both outputs share the same underlying values.
    Opens the .npz file once and closes it immediately.
    """
    p = cache_path(backbone, bin_mode, std_thresh, song_id)
    try:
        data = np.load(str(p))
    except (EOFError, OSError, ValueError):
        _purge_corrupt(p)
        return UnitTensor(np.empty((0, 0), dtype=np.float32)), UnitTensor(np.empty((0, 0), dtype=np.float32))
    try:
        norm_a = data[f"pool_{rep_a}_norm"].copy()
        norm_b = data[f"pool_{rep_b}_norm"].copy() if rep_b != rep_a else norm_a
    finally:
        data.close()
    return UnitTensor(norm_a), UnitTensor(norm_b)


def load_head_acts(
    backbone: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
) -> tuple[dict[str, np.ndarray], np.ndarray] | tuple[None, None]:
    """Load per-bin head activations and bin weights for one song.

    Returns
    -------
    (head_acts, weights)
        head_acts : dict mapping head_name -> float32 array [n_bins, n_classes]
        weights   : int32 array [n_bins]
    Returns (None, None) if no head arrays are present.
    """
    p = cache_path(backbone, bin_mode, std_thresh, song_id)
    if not p.exists():
        return None, None
    try:
        data = np.load(str(p))
    except (EOFError, OSError, ValueError):
        _purge_corrupt(p)
        return None, None
    try:
        head_keys = [k for k in data.files if k.startswith("head_")]
        if not head_keys:
            return None, None
        acts = {k[5:]: data[k].copy() for k in head_keys}  # strip "head_" prefix
        wts = (
            data["weights"].copy()
            if "weights" in data.files
            else np.ones(next(iter(acts.values())).shape[0], dtype=np.int32)
        )
    finally:
        data.close()
    return acts, wts
