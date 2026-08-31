"""Filesystem cache for flat PTC/CTP head activations.

Layout:
    {OUTPUT_ROOT}/cache/{backbone}/heads/{head_name}/{strategy}/{pathway}/{song_id}.npy

Each file is a float32 array of shape [n_classes]. File presence is the
canonical done signal — no DB query required.

Pathway is 'ptc' (pool-then-classify) or 'ctp' (classify-then-pool).
Strategy is the flat pooling strategy (mean, median, max, min).
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import numpy as _np

from scripts.embedding_research.config import OUTPUT_ROOT as _OUTPUT_ROOT
from scripts.embedding_research.helpers.cache_utils import build_done_set as _build_done_set
from scripts.embedding_research.helpers.cache_utils import missing_sids as _missing_sids

if TYPE_CHECKING:
    from pathlib import Path

_log = logging.getLogger(__name__)

_CACHE_ROOT = _OUTPUT_ROOT / "cache"


# ── Path helpers ──────────────────────────────────────────────────────────────


def _path(backbone: str, head_name: str, strategy: str, pathway: str, song_id: str) -> Path:
    return _CACHE_ROOT / backbone / "heads" / head_name / strategy / pathway / f"{song_id}.npy"


# ── Write ─────────────────────────────────────────────────────────────────────


def save(
    backbone: str,
    head_name: str,
    strategy: str,
    pathway: str,
    song_id: str,
    act: _np.ndarray,
) -> None:
    """Save a flat head activation to the filesystem cache."""
    p = _path(backbone, head_name, strategy, pathway, song_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    _np.save(str(p), _np.asarray(act, dtype=_np.float32))


# ── Read ──────────────────────────────────────────────────────────────────────


def load(
    backbone: str,
    head_name: str,
    strategy: str,
    pathway: str,
    song_id: str,
) -> _np.ndarray | None:
    """Load a flat head activation, or None if not cached or corrupt."""
    p = _path(backbone, head_name, strategy, pathway, song_id)
    if not p.exists():
        return None
    try:
        return _np.load(str(p))
    except (EOFError, OSError, ValueError) as exc:
        _log.warning("Corrupt flat head cache file %s: %s — deleting", p, exc)
        with contextlib.suppress(OSError):
            p.unlink()
        return None


def is_done(
    backbone: str,
    head_name: str,
    strategy: str,
    song_id: str,
    *,
    done_set_ptc: frozenset[str] | None = None,
    done_set_ctp: frozenset[str] | None = None,
) -> bool:
    """Return True iff both ptc and ctp activations are cached.

    Pass *done_set_ptc* and *done_set_ctp* (from :func:`build_done_set`) to
    avoid two ``stat()`` calls per song.  Corruption is detected and purged at
    load time by :func:`load`.
    """
    if done_set_ptc is not None and done_set_ctp is not None:
        return song_id in done_set_ptc and song_id in done_set_ctp
    return all(_path(backbone, head_name, strategy, pathway, song_id).exists() for pathway in ("ptc", "ctp"))


def missing_for_head(song_ids: list[str], backbone: str, head_name: str, strategy: str) -> list[str]:
    """Return song_ids missing either ptc or ctp activation. Zero-length files are purged."""
    ptc_dir = _CACHE_ROOT / backbone / "heads" / head_name / strategy / "ptc"
    ctp_dir = _CACHE_ROOT / backbone / "heads" / head_name / strategy / "ctp"
    missing_ptc = set(_missing_sids(song_ids, ptc_dir))
    missing_ctp = set(_missing_sids(song_ids, ctp_dir))
    return sorted(missing_ptc | missing_ctp)


def load_bulk(
    backbone: str,
    head_name: str,
    strategy: str,
    pathway: str,
    sids: list[str],
) -> dict[str, _np.ndarray]:
    """Load activations for multiple songs. Missing or corrupt files are omitted."""
    result: dict[str, _np.ndarray] = {}
    for sid in sids:
        act = load(backbone, head_name, strategy, pathway, sid)
        if act is not None:
            result[sid] = act
    return result


# ── Discovery ─────────────────────────────────────────────────────────────────


def list_done_sids(backbone: str, head_name: str, strategy: str) -> list[str]:
    """Return sorted song IDs where both ptc and ctp files exist."""
    ptc_dir = _CACHE_ROOT / backbone / "heads" / head_name / strategy / "ptc"
    ctp_dir = _CACHE_ROOT / backbone / "heads" / head_name / strategy / "ctp"
    ptc_sids = _build_done_set(ptc_dir)
    ctp_sids = _build_done_set(ctp_dir)
    return sorted(ptc_sids & ctp_sids)


def list_all_heads(backbone: str) -> list[str]:
    """Return sorted head names present in the cache for this backbone."""
    heads_dir = _CACHE_ROOT / backbone / "heads"
    if not heads_dir.exists():
        return []
    return sorted(d.name for d in heads_dir.iterdir() if d.is_dir())


def list_done_keys() -> set[tuple[str, str, str, str]]:
    """Return ``(song_id, backbone, head_name, strategy)`` for every fully-complete entry.

    An entry is considered complete when *both* the ``ptc`` and ``ctp`` pathway
    files exist.  Scans the directory tree once; callers should cache the result.
    """
    if not _CACHE_ROOT.exists():
        return set()
    out: set[tuple[str, str, str, str]] = set()
    for bb_dir in _CACHE_ROOT.iterdir():
        if not bb_dir.is_dir():
            continue
        heads_dir = bb_dir / "heads"
        if not heads_dir.is_dir():
            continue
        for hd_dir in heads_dir.iterdir():
            if not hd_dir.is_dir():
                continue
            for st_dir in hd_dir.iterdir():
                if not st_dir.is_dir():
                    continue
                ptc_dir = st_dir / "ptc"
                ctp_dir = st_dir / "ctp"
                if not ptc_dir.is_dir():
                    continue
                ctp_sids = {f.stem for f in ctp_dir.glob("*.npy")} if ctp_dir.is_dir() else set()
                for f in ptc_dir.glob("*.npy"):
                    if f.stem in ctp_sids:
                        out.add((f.stem, bb_dir.name, hd_dir.name, st_dir.name))
    return out
