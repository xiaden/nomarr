"""Shared filesystem cache utilities for the embedding research pipeline.

These helpers operate purely on directory structure — no cache-module-specific
knowledge. They form the canonical skip-guard for all embed phases.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

_log = logging.getLogger(__name__)


def missing_sids(
    song_ids: Iterable[str],
    cache_dir: Path,
    *,
    suffix: str = ".npy",
) -> list[str]:
    """Return the subset of *song_ids* not present (or zero-length) in *cache_dir*.

    Performs a single directory glob. Zero-length files are deleted on sight and
    treated as absent. Returns all *song_ids* if *cache_dir* does not exist.

    Args:
        song_ids: Candidate song IDs to check.
        cache_dir: Flat directory where each song is stored as
            ``{song_id}{suffix}``.
        suffix: File extension, default ``".npy"``.

    Returns:
        Sorted list of song IDs that have no valid cached file.
    """
    sids = list(song_ids)
    if not cache_dir.exists():
        return sorted(sids)

    done: set[str] = set()
    for p in cache_dir.glob(f"*{suffix}"):
        if p.stat().st_size == 0:
            try:
                p.unlink()
                _log.warning("Deleted zero-length cache file (will recompute): %s", p)
            except OSError as exc:
                _log.warning("Could not delete zero-length cache file %s: %s", p, exc)
        else:
            done.add(p.stem)

    return sorted(sid for sid in sids if sid not in done)
