"""Bin-level pooling: _pool_segment."""

from __future__ import annotations

import numpy as _np

from scripts.embedding_research.vector_types import RawTensor as _RawTensor
from scripts.embedding_research.vector_types import RawVector as _RawVector
from scripts.embedding_research.vector_types import UnitTensor as _UnitTensor
from scripts.embedding_research.vector_types import UnitVector as _UnitVector

from ._constants import _BIN_POOL_STRATEGIES


def _build_pool_payload(
    raw_patches: _RawTensor,
    unit_patches: _UnitTensor,
    indices: list[int],
    pool_fn,
) -> dict:
    """Build one pooled payload from shared raw+unit patch segments.

    Contract:
    - vec_raw  = pool(raw patches)
    - vec_norm = normalize(pool(unit patches))

    This keeps bin payload construction identical across strategies; only the
    source of ``indices`` may differ (e.g. PTC vs CTP segmentation source).
    """
    raw_seg = raw_patches.data[indices]
    unit_seg = unit_patches.data[indices]
    vec_unit = _UnitVector(pool_fn(unit_seg))
    return {
        "vec_raw": _RawVector(pool_fn(raw_seg)),
        "vec_norm": vec_unit,
        "vec_unit": vec_unit,
        "source_indices": [int(i) for i in indices],
        "selected_local_idx": None,
        "selected_global_idx": None,
        "medoid_centrality": None,
        "medoid_mean_similarity": None,
        "weight": len(indices),
    }


def select_medoid_index(unit_seg: _np.ndarray) -> tuple[int, float]:
    """Return (selected_local_idx, centrality) for cosine medoid over unit rows."""
    n = len(unit_seg)
    if n <= 1:
        return 0, 1.0
    sims = unit_seg @ unit_seg.T
    centrality = sims.mean(axis=1)
    # np.argmax is deterministic and returns the first index on ties.
    local_idx = int(_np.argmax(centrality))
    return local_idx, float(centrality[local_idx])


def _build_medoid_payload(
    raw_patches: _RawTensor,
    unit_patches: _UnitTensor,
    indices: list[int],
) -> dict:
    """Build medoid payload using one observed segment row for raw+unit vectors."""
    unit_seg = unit_patches.data[indices]
    selected_local_idx, centrality = select_medoid_index(unit_seg)
    selected_global_idx = int(indices[selected_local_idx])

    vec_raw = _RawVector(raw_patches.data[selected_global_idx])
    vec_unit = _UnitVector(unit_patches.data[selected_global_idx])
    return {
        "vec_raw": vec_raw,
        "vec_norm": vec_unit,
        "vec_unit": vec_unit,
        "source_indices": [int(i) for i in indices],
        "selected_local_idx": selected_local_idx,
        "selected_global_idx": selected_global_idx,
        "medoid_centrality": centrality,
        "medoid_mean_similarity": centrality,
        "weight": len(indices),
    }


def _pool_segment(
    raw_patches: _RawTensor,
    unit_patches: _UnitTensor,
    indices: list[int],
) -> dict[str, dict]:
    """Pool a set of patches into a single bin vector.

    vec_raw  — pooled raw patches; unnormalized.  Only valid for head models.
    vec_norm — pooled unit-normalized patches.  UnitVector setter re-normalizes
               on assignment so the result is always a unit vector (‖v‖ ≈ 1),
               keeping downstream cosine dot-products in [−1, 1].
    """
    pooled: dict[str, dict] = {}
    for name, fn in _BIN_POOL_STRATEGIES.items():
        pooled[name] = _build_pool_payload(raw_patches, unit_patches, indices, fn)
    pooled["medoid"] = _build_medoid_payload(raw_patches, unit_patches, indices)
    return pooled
