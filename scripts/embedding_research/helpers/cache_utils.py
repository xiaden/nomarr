"""Shared filesystem cache utilities for the embedding research pipeline.

These helpers operate purely on directory structure — no cache-module-specific
knowledge. They form the canonical skip-guard for all embed phases.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

_log = logging.getLogger(__name__)


def build_done_set(cache_dir: Path, suffix: str = ".npy") -> frozenset[str]:
    """Return frozenset of file stems present in *cache_dir*.

    Pure directory listing — no ``stat()`` calls. Suitable for building an
    in-memory skip-guard before iterating over many songs. Corrupt or
    zero-length files are **not** detected here; validation happens at load
    time in each cache module's ``load()`` function.

    Args:
        cache_dir: Flat directory where each song is stored as
            ``{song_id}{suffix}``.
        suffix: File extension, default ``".npy"``.

    Returns:
        frozenset of stems (song IDs) whose file exists in *cache_dir*.
    """
    if not cache_dir.exists():
        return frozenset()
    return frozenset(p.stem for p in cache_dir.iterdir() if p.suffix == suffix)


def missing_sids(
    song_ids: Iterable[str],
    cache_dir: Path,
    *,
    suffix: str = ".npy",
) -> list[str]:
    """Return the subset of *song_ids* not present in *cache_dir*.

    Performs a single directory listing — no ``stat()`` calls. Corrupt or
    zero-length files are detected and purged at load time, not here.
    Returns all *song_ids* if *cache_dir* does not exist.

    Args:
        song_ids: Candidate song IDs to check.
        cache_dir: Flat directory where each song is stored as
            ``{song_id}{suffix}``.
        suffix: File extension, default ``".npy"``.

    Returns:
        Sorted list of song IDs that have no cached file.
    """
    sids = list(song_ids)
    if not cache_dir.exists():
        return sorted(sids)

    done = build_done_set(cache_dir, suffix)
    return sorted(sid for sid in sids if sid not in done)
