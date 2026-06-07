"""Module-level constants derived from research config TOML."""

from __future__ import annotations

from collections.abc import Callable as _Callable
from collections.abc import Iterable as _Iterable

import numpy as _np

from scripts.embedding_research.helpers.toml import load_research_config as _load_research_config

_cfg = _load_research_config()

_ALLOWED_REP_TYPES: tuple[str, ...] = ("mean", "median", "medoid", "max", "min")
_ALLOWED_AGG_METHODS: tuple[str, ...] = ("mean", "median", "medoid", "max", "min")


def _validated_choices(name: str, values: _Iterable[str], allowed: tuple[str, ...]) -> list[str]:
    out = [str(v) for v in values]
    bad = sorted({v for v in out if v not in allowed})
    if bad:
        raise ValueError(f"Unknown {name}: {bad}. Allowed: {list(allowed)}")
    return out


AGG_METHODS: list[str] = _validated_choices(
    "pooling.agg_methods",
    _cfg.get("pooling", {}).get("agg_methods", ["mean", "median", "max", "min"]),
    _ALLOWED_AGG_METHODS,
)
REP_TYPES: list[str] = _validated_choices(
    "pooling.rep_types",
    _cfg.get("pooling", {}).get("rep_types", ["mean", "median", "max", "min"]),
    _ALLOWED_REP_TYPES,
)

if "medoid" in AGG_METHODS:
    raise ValueError("agg_method=medoid is not implemented; use agg_method=median with rep_type=medoid.")

SIM_METRICS: list[str] = _cfg.get("similarity", {}).get("metrics", ["cosine"])

_BACKBONE_SR: int = 16_000
_EXPECTED_ROWS_PER_CONFIG = len(REP_TYPES) * len(REP_TYPES) * len(SIM_METRICS) * len(AGG_METHODS)

_BIN_POOL_STRATEGIES: dict[str, _Callable[[_np.ndarray], _np.ndarray]] = {
    "mean": lambda x: x.mean(axis=0).astype(_np.float32),
    # coordinate-wise median (synthetic, not necessarily an observed segment row)
    "median": lambda x: _np.median(x, axis=0).astype(_np.float32),
    # medoid: actual observed patch closest to the centroid (not synthetic)
    "medoid": lambda x: x[int(_np.argmin(_np.linalg.norm(x - x.mean(axis=0), axis=1)))].astype(_np.float32),
    "max": lambda x: x.max(axis=0).astype(_np.float32),
    "min": lambda x: x.min(axis=0).astype(_np.float32),
}
