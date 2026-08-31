"""Disk-backed cache for pairwise raw-similarity arrays.

Each (backbone, strategy, sid_a, sid_b) tuple maps to a single .npz file
under OUTPUT_ROOT/cache/sim_pairs/. The pair key is order-independent:
(sid_a, sid_b) and (sid_b, sid_a) resolve to the same file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from scripts.embedding_research.config import OUTPUT_ROOT

if TYPE_CHECKING:
    from pathlib import Path


def _pair_path(backbone: str, strategy_name: str, sid_a: str, sid_b: str) -> Path:
    min_id = min(sid_a, sid_b)
    max_id = max(sid_a, sid_b)
    return OUTPUT_ROOT / "cache/sim_pairs" / backbone / strategy_name / f"{min_id}_{max_id}.npz"


def store_sim_pair(
    backbone: str,
    strategy_name: str,
    sid_a: str,
    sid_b: str,
    raw_sim: np.ndarray,
) -> None:
    """Persist a raw similarity array for a song pair, skipping if already cached.

    Serialises *raw_sim* as float32 in .npz format, preserving its shape so it
    can be reloaded with the original number of dimensions.  If the cache file
    already exists the function returns immediately without overwriting.

    Args:
        backbone: Embedding model identifier (used as a directory component).
        strategy_name: Pooling / aggregation strategy label.
        sid_a: Song ID of the first track.
        sid_b: Song ID of the second track.
        raw_sim: Similarity array to store (any shape, converted to float32).
    """
    path = _pair_path(backbone, strategy_name, sid_a, sid_b)
    if path.exists():
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        sim=raw_sim.ravel().astype(np.float32),
        shape=np.array(raw_sim.shape, dtype=np.int32),
    )


def load_sim_pair(
    backbone: str,
    strategy_name: str,
    sid_a: str,
    sid_b: str,
) -> np.ndarray | None:
    """Load a cached raw similarity array for a song pair.

    Reconstructs the array with its original shape.  Returns *None* if no cache
    file exists for the given key.

    Args:
        backbone: Embedding model identifier.
        strategy_name: Pooling / aggregation strategy label.
        sid_a: Song ID of the first track.
        sid_b: Song ID of the second track.

    Returns:
        The stored similarity array, or *None* if the pair has not been cached.
    """
    path = _pair_path(backbone, strategy_name, sid_a, sid_b)
    if not path.exists():
        return None

    with np.load(path) as data:
        return data["sim"].reshape(data["shape"])


def sim_pair_exists(
    backbone: str,
    strategy_name: str,
    sid_a: str,
    sid_b: str,
) -> bool:
    """Return True if a cache file exists for the given song pair.

    Args:
        backbone: Embedding model identifier.
        strategy_name: Pooling / aggregation strategy label.
        sid_a: Song ID of the first track.
        sid_b: Song ID of the second track.

    Returns:
        True when the pair is cached, False otherwise.
    """
    return _pair_path(backbone, strategy_name, sid_a, sid_b).exists()
