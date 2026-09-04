"""Filesystem cache for per-bin mean PTC head activations.

**ARCHIVAL (read-only compatibility).** This module and its readers are a legacy copied-head cache for
GOLDEN COMPARISONS only. The primary analysis path (catalog memberships + disposable search views, see
``common/catalog_analysis.py``) never reads these files and never falls back to them. Do not write new
producers/consumers against this path.

PTC (Pool-Then-Classify) segmentation drives bin boundaries from the pooled
embedding stream.  This module stores the mean head-activation vector for each
PTC bin so that downstream analysis can compare against CTP head activations
without re-running inference.

The follow-on **shared PTC boundary** head phase (Plan B) writes these entries
and extends each ``.npz`` with explicit phase/source provenance metadata:
``boundary_source="effnet_ptc"``, ``bin_start_idx`` / ``bin_end_idx``
boundary arrays, ``scoring_semantics_version``, and ``finite`` status.  The
immutable/versioned root behavior is retained — this is the same cache root,
extended in place, and CTP cache paths are never repurposed.

Layout::

    {CACHE_BASE}/{backbone}/{head}/{bin_mode}/{std_thresh:.3f}/{song_id}.npz

npz contents
------------
acts                        [n_bins, C] float32 — mean head activation per bin
weights                     [n_bins]    int32   — patch count per bin
bin_start_idx               [n_bins]    int32   — first patch index per bin (EffNet PTC boundary)
bin_end_idx                 [n_bins]    int32   — last patch index per bin (EffNet PTC boundary)
boundary_source             [1]         <U     — "effnet_ptc" (never a CTP path)
backbone                    [1]         <U     — backbone name
head                        [1]         <U     — head name
bin_mode                    [1]         <U     — binning mode
threshold                   [1]         f8     — canonical std threshold
song_id                     [1]         <U     — song ID
scoring_semantics_version   [1]         int32   — scoring-semantics provenance
finite                      [1]         int32   — 1 iff every emitted numeric value is finite
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from scripts.embedding_research.cache_identity import (
    SCORING_SEMANTICS_VERSION as _SCORING_SEMANTICS_VERSION,
)
from scripts.embedding_research.config import OUTPUT_ROOT as _OUTPUT_ROOT
from scripts.embedding_research.helpers.binning import cache_semantics_tag as _cache_semantics_tag
from scripts.embedding_research.helpers.binning import threshold_key as _threshold_key

if TYPE_CHECKING:
    from pathlib import Path

_log = logging.getLogger(__name__)

CACHE_BASE: Path = _OUTPUT_ROOT / "cache" / "binned_ptc_heads" / _cache_semantics_tag()

#: The only boundary source this cache may hold.  CTP cache paths are never
#: repurposed; entries carrying any other boundary source are rejected as stale.
BOUNDARY_SOURCE_EFFNET_PTC = "effnet_ptc"


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
    *,
    bin_start_idx: np.ndarray | None = None,
    bin_end_idx: np.ndarray | None = None,
    boundary_source: str = BOUNDARY_SOURCE_EFFNET_PTC,
    scoring_semantics_version: int = _SCORING_SEMANTICS_VERSION,
    finite: bool | None = None,
) -> None:
    """Save per-bin mean head activations to the filesystem cache.

    Parameters
    ----------
    acts:
        ``[n_bins, C]`` float32 — mean head-activation vector per bin.
    weights:
        ``[n_bins]`` int32 — patch count per bin.
    bin_start_idx, bin_end_idx:
        ``[n_bins]`` int32 — inclusive EffNet PTC bin boundary arrays.  When
        omitted, an all-``-1`` array is written so the provenance field is
        always present.
    boundary_source:
        Phase/source provenance.  Only ``"effnet_ptc"`` is written by this
        cache; CTP cache paths are never repurposed.
    scoring_semantics_version:
        Scoring-semantics provenance folded into the cache entry so stale
        semantic roots can be rejected without rewriting old bytes.
    finite:
        Finite status of the emitted values.  When omitted it is derived from
        ``acts``.
    """
    if acts.size == 0:
        return
    p = cache_path(backbone, head, bin_mode, std_thresh, song_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    n_bins = int(np.asarray(acts).shape[0])
    default_idx = np.full(n_bins, -1, dtype=np.int32)
    if finite is None:
        finite = bool(np.all(np.isfinite(acts)))
    np.savez(
        str(p),
        acts=np.asarray(acts, dtype=np.float32),
        weights=np.asarray(weights, dtype=np.int32),
        bin_start_idx=np.asarray(bin_start_idx, dtype=np.int32) if bin_start_idx is not None else default_idx,
        bin_end_idx=np.asarray(bin_end_idx, dtype=np.int32) if bin_end_idx is not None else default_idx,
        boundary_source=np.array([boundary_source]),
        backbone=np.array([backbone]),
        head=np.array([head]),
        bin_mode=np.array([bin_mode]),
        threshold=np.array([float(std_thresh)]),
        song_id=np.array([song_id]),
        scoring_semantics_version=np.array([scoring_semantics_version], dtype=np.int32),
        finite=np.array([1 if finite else 0], dtype=np.int32),
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


def load_metadata(
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
) -> dict | None:
    """Load the full provenance metadata for one cached song.

    Returns a dict with ``acts``, ``weights``, ``bin_start_idx``, ``bin_end_idx``,
    ``boundary_source``, ``backbone``, ``head``, ``bin_mode``, ``threshold``,
    ``song_id``, ``scoring_semantics_version``, and ``finite``, or ``None`` if
    the file is absent or corrupt.  Fields written by the extended save are
    always present; a legacy file lacking the provenance keys yields ``None``
    for those fields (treated as stale by :func:`validate_boundary_source`).
    """
    p = cache_path(backbone, head, bin_mode, std_thresh, song_id)
    if not p.exists():
        return None
    try:
        data = np.load(str(p))
        meta: dict = {
            "acts": data["acts"].copy(),
            "weights": data["weights"].copy(),
        }
        meta["bin_start_idx"] = data["bin_start_idx"].copy() if "bin_start_idx" in data.files else None
        meta["bin_end_idx"] = data["bin_end_idx"].copy() if "bin_end_idx" in data.files else None
        meta["boundary_source"] = str(data["boundary_source"][0]) if "boundary_source" in data.files else None
        meta["scoring_semantics_version"] = (
            int(data["scoring_semantics_version"][0]) if "scoring_semantics_version" in data.files else None
        )
        meta["finite"] = bool(data["finite"][0]) if "finite" in data.files else None
        meta["backbone"] = str(data["backbone"][0]) if "backbone" in data.files else None
        meta["head"] = str(data["head"][0]) if "head" in data.files else None
        meta["bin_mode"] = str(data["bin_mode"][0]) if "bin_mode" in data.files else None
        meta["threshold"] = float(data["threshold"][0]) if "threshold" in data.files else None
        meta["song_id"] = str(data["song_id"][0]) if "song_id" in data.files else None
        data.close()
        return meta
    except (EOFError, OSError, ValueError, KeyError):
        _purge_corrupt(p)
        return None


def validate_boundary_source(
    metadata: dict | None,
    *,
    expected_boundary_source: str = BOUNDARY_SOURCE_EFFNET_PTC,
    expected_scoring_semantics_version: int = _SCORING_SEMANTICS_VERSION,
) -> None:
    """Reject stale provenance on a cached head-phase entry.

    A ``None`` *metadata* (absent/corrupt file) or an entry whose
    ``boundary_source`` is not ``effnet_ptc`` (never a CTP path) or whose
    ``scoring_semantics_version`` differs from the current one raises
    ``ValueError`` — stale entries are rejected, never silently reused.
    """
    if metadata is None:
        raise ValueError("cached head-phase entry absent or corrupt (stale source)")
    stored_source = metadata.get("boundary_source")
    if stored_source != expected_boundary_source:
        raise ValueError(
            f"head-phase cache entry has boundary_source={stored_source!r}; expected "
            f"{expected_boundary_source!r}. CTP cache paths must not be repurposed and stale "
            "sources are rejected."
        )
    stored_semantics = metadata.get("scoring_semantics_version")
    if stored_semantics != expected_scoring_semantics_version:
        raise ValueError(
            f"head-phase cache entry carries scoring_semantics_version={stored_semantics!r}; "
            f"expected {expected_scoring_semantics_version!r}. Stale semantics are rejected, "
            "not silently reused."
        )


def check_cache_valid(
    backbone: str,
    head: str,
    bin_mode: str,
    std_thresh: float,
    song_id: str,
    *,
    expected_boundary_source: str = BOUNDARY_SOURCE_EFFNET_PTC,
    expected_scoring_semantics_version: int = _SCORING_SEMANTICS_VERSION,
) -> bool:
    """Return True iff the cached entry exists and carries non-stale provenance."""
    metadata = load_metadata(backbone, head, bin_mode, std_thresh, song_id)
    if metadata is None:
        return False
    try:
        validate_boundary_source(
            metadata,
            expected_boundary_source=expected_boundary_source,
            expected_scoring_semantics_version=expected_scoring_semantics_version,
        )
    except ValueError:
        return False
    return True
