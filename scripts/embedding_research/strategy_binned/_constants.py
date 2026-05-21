"""Module-level constants derived from research config TOML."""

from __future__ import annotations

from collections.abc import Callable as _Callable

import numpy as _np

from ..helpers.toml import load_research_config as _load_research_config

_cfg = _load_research_config()

AGG_METHODS: list[str] = _cfg.get("pooling", {}).get("agg_methods", ["mean", "median", "max", "min"])
REP_TYPES: list[str] = _cfg.get("pooling", {}).get("rep_types", ["mean", "median", "max", "min"])
SIM_METRICS: list[str] = _cfg.get("similarity", {}).get("metrics", ["cosine", "l2"])

_BACKBONE_SR: int = 16_000
_EXPECTED_ROWS_PER_CONFIG = len(REP_TYPES) * len(REP_TYPES) * len(SIM_METRICS) * len(AGG_METHODS)

_BIN_POOL_STRATEGIES: dict[str, _Callable[[_np.ndarray], _np.ndarray]] = {
    "mean": lambda x: x.mean(axis=0).astype(_np.float32),
    "median": lambda x: _np.median(x, axis=0).astype(_np.float32),
    "max": lambda x: x.max(axis=0).astype(_np.float32),
    "min": lambda x: x.min(axis=0).astype(_np.float32),
}
