"""Bin-level pooling: _pool_segment."""

from __future__ import annotations

import numpy as _np

from ._constants import _BIN_POOL_STRATEGIES


def _pool_segment(
    raw_patches: _np.ndarray,
    norm_patches: _np.ndarray,
    indices: list[int],
) -> dict[str, dict]:
    raw_seg = raw_patches[indices]
    norm_seg = norm_patches[indices]
    weight = len(indices)

    pooled: dict[str, dict] = {}
    for name, fn in _BIN_POOL_STRATEGIES.items():
        pooled[name] = {
            "vec_raw": fn(raw_seg),
            "vec_norm": fn(norm_seg),
            "weight": weight,
        }
    return pooled
