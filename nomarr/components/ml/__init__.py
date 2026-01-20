"""
Ml package.
"""

from .ml_audio_comp import HAVE_ESSENTIA, load_audio_mono, should_skip_short
from .ml_cache_comp import (
    backbone_cache_key,
    cache_backbone_predictor,
    cache_key,
    check_and_evict_idle_cache,
    clear_predictor_cache,
    get_backbone_cache_size,
    get_cache_idle_time,
    get_cache_size,
    get_cached_backbone_predictor,
    is_initialized,
    touch_cache,
    warmup_predictor_cache,
)
from .ml_calibration_comp import apply_minmax_calibration, save_calibration_sidecars
from .ml_inference_comp import (
    compute_embeddings_for_backbone,
    make_head_only_predictor_batched,
    make_predictor_uncached,
)

__all__ = [
    "HAVE_ESSENTIA",
    "apply_minmax_calibration",
    "backbone_cache_key",
    "cache_backbone_predictor",
    "cache_key",
    "check_and_evict_idle_cache",
    "clear_predictor_cache",
    "compute_embeddings_for_backbone",
    "get_backbone_cache_size",
    "get_cache_idle_time",
    "get_cache_size",
    "get_cached_backbone_predictor",
    "is_initialized",
    "load_audio_mono",
    "make_head_only_predictor_batched",
    "make_predictor_uncached",
    "save_calibration_sidecars",
    "should_skip_short",
    "touch_cache",
    "warmup_predictor_cache",
]
