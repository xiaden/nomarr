"""Filesystem cache for per-bin mean PTC head activations.

PTC (Pool-Then-Classify) segmentation drives bin boundaries from the pooled
embedding stream.  This module stores the mean head-activation vector for each
PTC bin so that downstream analysis can compare against CTP head activations
without re-running inference.

Layout::

    {CACHE_BASE}/{backbone}/{head}/{bin_mode}/{std_thresh:.3f}/{song_id}.npz

npz contents
------------
acts     [n_bins, C] float32 — mean head activation per bin
weights  [n_bins]    int32   — patch count per bin
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from scripts.embedding_research.config import OUTPUT_ROOT as _OUTPUT_ROOT
from scripts.embedding_research.helpers.binning import cache_semantics_tag as _cache_semantics_tag
from scripts.embedding_research.helpers.binning import threshold_key as _threshold_key

_log = logging.getLogger(__name__)

CACHE_BASE: Path = _OUTPUT_ROOT / "cache" / "binned_ptc_heads" / _cache_semantics_tag()


def _purge_corrupt(p: Path) -> None:
    try:
        p.unlink()
        _log.warning("Deleted corrupt PTC-heads cache file (will recompute): %s", p)
    except OSError as e:
        _log.warning("Could not delete corrupt PTC-heads cache file %s: %s", p, e)


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


def is_done(
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
    *,
    done_set: frozenset[str] | None = None,
) -> bool:
    """Return True iff the npz for this combo is cached.

    Pass *done_set* (from :func:`build_done_set`) to avoid a ``stat()`` call
    per song.  Corruption is detected and purged at load time by :func:`load`.
    """
    if done_set is not None:
        return song_id in done_set
    return cache_path(backbone, head, bin_mode, std_thresh, song_id).exists()


def list_done_keys() -> set[tuple[str, str, str, str, float]]:
    """Return ``(song_id, backbone, head, bin_mode, std_thresh)`` for every cached file.

    Scans the directory tree once; callers should cache the result.
    """
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
    acts: np.ndarray,
    weights: np.ndarray,
) -> None:
    """Save per-bin mean head activations to the filesystem cache.

    Parameters
    ----------
    acts:
        ``[n_bins, C]`` float32 — mean head-activation vector per bin.
    weights:
        ``[n_bins]`` int32 — patch count per bin.
    """
    if acts.size == 0:
        return
    p = cache_path(backbone, head, bin_mode, std_thresh, song_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        str(p),
        acts=np.asarray(acts, dtype=np.float32),
        weights=np.asarray(weights, dtype=np.int32),
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def load(
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Load per-bin activations for one song.

    Returns
    -------
    ``(acts, weights)`` where *acts* is ``[n_bins, C]`` float32 and
    *weights* is ``[n_bins]`` int32, or ``None`` if the file is absent or corrupt.
    """
    p = cache_path(backbone, head, bin_mode, std_thresh, song_id)
    if not p.exists():
        return None
    try:
        data = np.load(str(p))
        acts = data["acts"].copy()
        weights = data["weights"].copy()
        data.close()
        return acts, weights
    except (EOFError, OSError, ValueError, KeyError):
        _purge_corrupt(p)
        return None
