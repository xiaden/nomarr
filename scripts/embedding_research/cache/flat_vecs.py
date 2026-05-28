"""Filesystem cache for flat pooled vectors.

Layout:
    {OUTPUT_ROOT}/cache/{backbone}/{strategy}/flat/{song_id}.npy

Each file is a float32 array of shape [embed_dim]. Presence of the file is
the canonical signal that this (song, backbone, strategy) combination is done —
no DB query required.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from scripts.embedding_research.config import OUTPUT_ROOT as _OUTPUT_ROOT
from scripts.embedding_research.helpers.cache_utils import missing_sids as _missing_sids
from scripts.embedding_research.vector_types import RawTensor

_log = logging.getLogger(__name__)

_CACHE_ROOT = _OUTPUT_ROOT / "cache"


def _purge_corrupt(p: Path) -> None:
    try:
        p.unlink()
        _log.warning("Deleted corrupt cache file (will recompute): %s", p)
    except OSError as e:
        _log.warning("Could not delete corrupt cache file %s: %s", p, e)


# ── Path helpers ──────────────────────────────────────────────────────────────


def _vec_path(song_id: str, backbone: str, strategy: str) -> Path:
    return _CACHE_ROOT / backbone / strategy / "flat" / f"{song_id}.npy"


# ── Write ─────────────────────────────────────────────────────────────────────


def save_pooled(song_id: str, backbone: str, strategy: str, vec: np.ndarray) -> None:
    """Atomically save a pooled vector to the filesystem cache."""
    p = _vec_path(song_id, backbone, strategy)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(p), vec.astype(np.float32))


# ── Read ──────────────────────────────────────────────────────────────────────


def is_done(song_id: str, backbone: str, strategy: str) -> bool:
    """Return True if the pooled vec for this (song, backbone, strategy) is on disk and readable."""
    p = _vec_path(song_id, backbone, strategy)
    if not p.exists():
        return False
    if p.stat().st_size == 0:
        _purge_corrupt(p)
        return False
    try:
        np.load(str(p))
        return True
    except (EOFError, OSError, ValueError):
        _purge_corrupt(p)
        return False


def list_done_keys() -> set[tuple[str, str, str]]:
    """Return ``(song_id, backbone, strategy)`` for every cached file.

    Scans the directory tree once; callers should cache the result.
    """
    if not _CACHE_ROOT.exists():
        return set()
    out: set[tuple[str, str, str]] = set()
    for bb_dir in _CACHE_ROOT.iterdir():
        if not bb_dir.is_dir():
            continue
        for strat_dir in bb_dir.iterdir():
            if not strat_dir.is_dir():
                continue
            flat_dir = strat_dir / "flat"
            if not flat_dir.is_dir():
                continue
            for f in flat_dir.glob("*.npy"):
                out.add((f.stem, bb_dir.name, strat_dir.name))
    return out


def missing_for_strategy(song_ids: list[str], backbone: str, strategy: str) -> list[str]:
    """Return song_ids not yet cached for this (backbone, strategy). Zero-length files are purged."""
    return _missing_sids(song_ids, _CACHE_ROOT / backbone / strategy / "flat")


def load_pooled(song_id: str, backbone: str, strategy: str) -> np.ndarray | None:
    """Load a single pooled vec, or None if not cached or corrupt."""
    p = _vec_path(song_id, backbone, strategy)
    if not p.exists():
        return None
    if p.stat().st_size == 0:
        _purge_corrupt(p)
        return None
    try:
        return np.load(str(p))
    except (EOFError, OSError, ValueError):
        _purge_corrupt(p)
        return None


# ── Discovery ─────────────────────────────────────────────────────────────────


def list_done_sids(backbone: str, strategy: str) -> list[str]:
    """Return sorted list of song IDs that have a cached pooled vec. Zero-length files are purged."""
    d = _CACHE_ROOT / backbone / strategy / "flat"
    if not d.exists():
        return []
    valid = []
    for p in d.glob("*.npy"):
        if p.stat().st_size == 0:
            _purge_corrupt(p)
        else:
            valid.append(p.stem)
    return sorted(valid)


def list_configs() -> set[tuple[str, str]]:
    """Return all (backbone, strategy) pairs that have at least one pooled vec on disk."""
    if not _CACHE_ROOT.exists():
        return set()
    configs: set[tuple[str, str]] = set()
    for bb_dir in _CACHE_ROOT.iterdir():
        if not bb_dir.is_dir():
            continue
        for strat_dir in bb_dir.iterdir():
            if not strat_dir.is_dir():
                continue
            flat_dir = strat_dir / "flat"
            if flat_dir.is_dir() and any(flat_dir.glob("*.npy")):
                configs.add((bb_dir.name, strat_dir.name))
    return configs


# ── Bulk load ─────────────────────────────────────────────────────────────────


def load_matrix(
    backbone: str,
    strategy: str,
    con=None,
) -> tuple[RawTensor, list[str], list[str], list[str], list[str]]:
    """Load all pooled vecs for (backbone, strategy) from the filesystem cache.

    Returns (vecs [n, d], sids, artists, albums, genres).
    Metadata (artist/album/genre) is joined from the songs DB table when con is
    provided; otherwise defaults to ``"unknown"`` for all songs.
    """
    sids = list_done_sids(backbone, strategy)
    if not sids:
        return RawTensor(np.empty((0, 0), dtype=np.float32)), [], [], [], []

    arrays: list[np.ndarray] = []
    valid_sids: list[str] = []
    for sid in sids:
        v = load_pooled(sid, backbone, strategy)
        if v is not None:
            arrays.append(v)
            valid_sids.append(sid)

    if not arrays:
        return RawTensor(np.empty((0, 0), dtype=np.float32)), [], [], [], []

    vecs = RawTensor(np.stack(arrays, axis=0))

    if con is None:
        n = len(valid_sids)
        return vecs, valid_sids, ["unknown"] * n, ["unknown"] * n, ["unknown"] * n

    placeholders = ",".join("?" * len(valid_sids))
    rows = con.execute(
        f"SELECT song_id, artist, album, genre FROM songs WHERE song_id IN ({placeholders})",
        valid_sids,
    ).fetchall()
    meta: dict[str, tuple[str, str, str]] = {
        r[0]: (r[1] or "unknown", r[2] or "unknown", r[3] or "unknown") for r in rows
    }
    _unk = ("unknown", "unknown", "unknown")
    artists = [meta.get(sid, _unk)[0] for sid in valid_sids]
    albums = [meta.get(sid, _unk)[1] for sid in valid_sids]
    genres = [meta.get(sid, _unk)[2] for sid in valid_sids]
    return vecs, valid_sids, artists, albums, genres
