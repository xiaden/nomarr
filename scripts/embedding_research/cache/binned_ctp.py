"""Filesystem cache for CTP-derived binned embeddings.

CTP (Classifier-Then-Pool) segments are driven by a head's score-stream
STD-binning rather than embedding-space distance. The extra ``head`` dimension
is encoded in the path so each head gets its own slice.

Layout:
    {CACHE_BASE}/{backbone}/{head}/{bin_mode}/{std_thresh:.3f}/{song_id}.npz

npz contents
------------
pool_{strategy}_raw   [n_bins, D] float32   — unnormalised bin pooled vector
pool_{strategy}_norm  [n_bins, D] float32   — L2-normalised bin pooled vector
weights               [n_bins]    int32      — patch count per bin
outliers              [n_bins]    int32      — outlier count per bin

The DB table ``binned_ctp_vecs`` has been removed; this module replaces it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from scripts.embedding_research.config import OUTPUT_ROOT as _OUTPUT_ROOT
from scripts.embedding_research.helpers.binning import cache_semantics_tag as _cache_semantics_tag
from scripts.embedding_research.helpers.binning import threshold_key as _threshold_key

_log = logging.getLogger(__name__)

CACHE_BASE: Path = _OUTPUT_ROOT / "cache" / "binned_ctp" / _cache_semantics_tag()


def _purge_corrupt(p: Path) -> None:
    try:
        p.unlink()
        _log.warning("Deleted corrupt CTP cache file (will recompute): %s", p)
    except OSError as e:
        _log.warning("Could not delete corrupt CTP cache file %s: %s", p, e)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def cache_path(backbone: str, head: str, bin_mode: str, std_thresh: float, song_id: str) -> Path:
    return CACHE_BASE / backbone / head / bin_mode / _threshold_key(std_thresh) / f"{song_id}.npz"


def config_dir(backbone: str, head: str, bin_mode: str, std_thresh: float) -> Path:
    return CACHE_BASE / backbone / head / bin_mode / _threshold_key(std_thresh)


# ---------------------------------------------------------------------------
# Completion checks
# ---------------------------------------------------------------------------


def is_done(backbone: str, head: str, bin_mode: str, std_thresh: float, song_id: str) -> bool:
    """Return True iff the CTP npz for this (song, backbone, head, bin_mode, std_thresh) exists and is readable."""
    p = cache_path(backbone, head, bin_mode, std_thresh, song_id)
    if not p.exists():
        return False
    try:
        data = np.load(str(p))
        data.close()
        return True
    except (EOFError, OSError, ValueError):
        _purge_corrupt(p)
        return False


def query_ctp_configs() -> set[tuple[str, str, str, float]]:
    """Return ``(backbone, head, bin_mode, std_thresh)`` for every non-empty config directory."""
    if not CACHE_BASE.exists():
        return set()
    out: set[tuple[str, str, str, float]] = set()
    for bb_dir in CACHE_BASE.iterdir():
        if not bb_dir.is_dir():
            continue
        for hd_dir in bb_dir.iterdir():
            if not hd_dir.is_dir():
                continue
            for bm_dir in hd_dir.iterdir():
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
                        out.add((bb_dir.name, hd_dir.name, bm_dir.name, th))
    return out


def list_done_keys() -> set[tuple[str, str, str, str, float]]:
    """Return ``(song_id, backbone, head, bin_mode, std_thresh)`` for every cached file."""
    if not CACHE_BASE.exists():
        return set()
    out: set[tuple[str, str, str, str, float]] = set()
    for bb_dir in CACHE_BASE.iterdir():
        if not bb_dir.is_dir():
            continue
        for hd_dir in bb_dir.iterdir():
            if not hd_dir.is_dir():
                continue
            for bm_dir in hd_dir.iterdir():
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
                        out.add((f.stem, bb_dir.name, hd_dir.name, bm_dir.name, th))
    return out


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def save(
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
    bulk_vecs: list[tuple],
) -> None:
    """Write one song's CTP binned vecs to an npz file.

    Parameters
    ----------
    bulk_vecs:
        Rows with schema
        ``(sid, backbone, head, bin_mode, std_thresh, bin_id, pool_strategy,
              vec_raw_bytes, vec_norm_bytes, weight, outlier_count,
              selected_global_idx, selected_local_idx, medoid_centrality,
              bin_start_idx, bin_end_idx)``
        — the exact format produced by ``_process_song_head_missing`` in classify.py.
    """
    if not bulk_vecs:
        return

    bins: dict[int, dict] = {}
    for row in bulk_vecs:
        _, _, _, _, _, bin_id, pool_strategy, raw_b, norm_b, weight, outlier_count, *meta = row
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
            }
        bins[bin_id]["pools"][pool_strategy] = {
            "raw": np.frombuffer(raw_b, dtype=np.float32).copy(),
            "norm": np.frombuffer(norm_b, dtype=np.float32).copy(),
            "selected_global_idx": selected_global_idx,
            "selected_local_idx": selected_local_idx,
            "centrality": centrality,
        }

    if not bins:
        return

    sorted_ids = sorted(bins.keys())
    first = bins[sorted_ids[0]]
    strategies = sorted(first["pools"])

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

    p = cache_path(backbone, head, bin_mode, std_thresh, song_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez(str(p), **arrays)
    _log.info(
        "ctp_cache.save  %s/%s/%s/%.3f/%s  bins=%d strats=%d",
        backbone,
        head,
        bin_mode,
        std_thresh,
        song_id,
        len(sorted_ids),
        len(strategies),
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def load_all_reps(
    con,
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    song_ids: frozenset[str] | None = None,
) -> tuple[list[str], list[str], list[list[dict]]]:
    """Load all four pool-strategy CTP vectors for every bin of every song.

    Reads from the filesystem cache (``binned_ctp_cache``).  The ``con``
    argument is used only to look up artist labels from the ``songs`` table.

    Returns
    -------
    sids       : list[str]         - song_id per song (sorted)
    artists    : list[str]         - artist label per song
    song_data  : list[list[dict]]  - per-song list of bin dicts, each with keys:
                   bin_id, weight, outlier_count,
                   vec_{strategy}_raw and (when present) vec_{strategy}_norm
                   for each pool strategy (float32 arrays)

    Songs missing any of the four pool strategies for any bin are excluded.
    """
    d = config_dir(backbone, head, bin_mode, std_thresh)
    _log.info("load_all_reps: scanning %s", d)
    if not d.exists():
        _log.info("load_all_reps: path does not exist — 0 songs")
        return [], [], []

    npz_files = sorted(d.glob("*.npz"))
    if song_ids is not None:
        npz_files = [f for f in npz_files if f.stem in song_ids]

    if not npz_files:
        _log.info("load_all_reps: 0 .npz files found")
        return [], [], []

    # Look up artist labels in one query
    candidate_sids = [f.stem for f in npz_files]
    artist_rows = con.execute(
        "SELECT song_id, artist FROM songs WHERE song_id = ANY(?)",
        [candidate_sids],
    ).fetchall()
    artist_map: dict[str, str] = {sid: (artist or "unknown") for sid, artist in artist_rows}

    from scripts.embedding_research.strategy_binned._constants import _BIN_POOL_STRATEGIES

    required = {f"pool_{name}_raw" for name in _BIN_POOL_STRATEGIES}
    suffix_raw = "_raw"
    suffix_norm = "_norm"

    sids: list[str] = []
    artists: list[str] = []
    song_data: list[list[dict]] = []

    for f in npz_files:
        sid = f.stem
        try:
            data = np.load(str(f))
        except (EOFError, OSError, ValueError):
            _purge_corrupt(f)
            continue
        try:
            if not required.issubset(set(data.files)):
                missing = required - set(data.files)
                _log.info("load_all_reps: skip %s — missing pool keys: %s", sid, sorted(missing))
                continue
            n_bins = int(data["weights"].shape[0])
            strategies = sorted(
                k[5 : -len(suffix_raw)] for k in data.files if k.startswith("pool_") and k.endswith(suffix_raw)
            )
            bins_list: list[dict] = []
            complete = True
            for i in range(n_bins):
                b: dict = {
                    "bin_id": i,
                    "weight": int(data["weights"][i]),
                    "outlier_count": int(data["outliers"][i]),
                    "bin_start_idx": int(data["bin_start_idx"][i]) if "bin_start_idx" in data.files else -1,
                    "bin_end_idx": int(data["bin_end_idx"][i]) if "bin_end_idx" in data.files else -1,
                }
                for st in strategies:
                    raw_key = f"pool_{st}{suffix_raw}"
                    norm_key = f"pool_{st}{suffix_norm}"
                    if raw_key not in data.files:
                        complete = False
                        break
                    # Compatibility: keep vec_{st} as raw alias for callers that
                    # still expect the historical key.
                    b[f"vec_{st}"] = data[raw_key][i].copy()
                    b[f"vec_{st}_raw"] = data[raw_key][i].copy()
                    if norm_key in data.files:
                        b[f"vec_{st}_norm"] = data[norm_key][i].copy()
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
                if not complete:
                    break
                bins_list.append(b)
        finally:
            data.close()

        if complete and bins_list:
            sids.append(sid)
            artists.append(artist_map.get(sid, "unknown"))
            song_data.append(bins_list)

    return sids, artists, song_data
