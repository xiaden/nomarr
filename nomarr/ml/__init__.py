"""
Ml package.
"""

from .backend_essentia import get_version, is_available, require
from .cache import (
    cache_key,
    check_and_evict_idle_cache,
    clear_predictor_cache,
    get_cache_idle_time,
    get_cache_size,
    is_initialized,
    touch_cache,
    warmup_predictor_cache,
)
from .calibration import apply_minmax_calibration, generate_minmax_calibration, save_calibration_sidecars
from .inference import compute_embeddings_for_backbone, make_head_only_predictor_batched, make_predictor_uncached

__all__ = [
    "apply_minmax_calibration",
    "cache_key",
    "check_and_evict_idle_cache",
    "clear_predictor_cache",
    "compute_embeddings_for_backbone",
    "generate_minmax_calibration",
    "get_cache_idle_time",
    "get_cache_size",
    "get_version",
    "is_available",
    "is_initialized",
    "make_head_only_predictor_batched",
    "make_predictor_uncached",
    "require",
    "save_calibration_sidecars",
    "touch_cache",
    "warmup_predictor_cache",
]
