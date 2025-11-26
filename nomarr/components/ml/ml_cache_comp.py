"""
Predictor cache management for TensorFlow models.

Manages global cache of model predictors to avoid repeated model loading overhead.
Supports automatic cache eviction after idle timeout to free GPU memory.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from nomarr.components.ml.ml_discovery_comp import HeadInfo

# Global predictor cache: {cache_key: predict_fn}
# Cache key must be unique across backbones to avoid collisions
_PREDICTOR_CACHE: dict[str, Callable[[np.ndarray, int], np.ndarray]] = {}
_CACHE_INITIALIZED = False
_CACHE_LAST_ACCESS: float = 0.0
_CACHE_LOCK = threading.Lock()
_CACHE_TIMEOUT: int = 300  # seconds (0 = never evict)


def cache_key(head_info: HeadInfo) -> str:
    """Unique cache key for a head across backbones/types."""
    return f"{head_info.name}::{head_info.backbone}::{head_info.head_type}"


def is_initialized() -> bool:
    """Check if cache has been initialized."""
    return _CACHE_INITIALIZED


def get_cache_size() -> int:
    """Return number of predictors in cache."""
    return len(_PREDICTOR_CACHE)


def warmup_predictor_cache(
    models_dir: str,
    cache_idle_timeout: int = 300,
) -> int:
    """
    Pre-load all model predictors into cache to avoid loading overhead during processing.
    Returns the number of predictors cached.

    Args:
        models_dir: Directory containing model files
        cache_idle_timeout: Seconds before idle cache eviction (0 = never evict, default: 300)
    """
    global _PREDICTOR_CACHE, _CACHE_INITIALIZED, _CACHE_LAST_ACCESS
    global _CACHE_TIMEOUT

    # Store cache config
    _CACHE_TIMEOUT = cache_idle_timeout

    if _CACHE_INITIALIZED:
        logging.info("[cache] Predictor cache already initialized")
        return len(_PREDICTOR_CACHE)

    from nomarr.components.ml.ml_discovery_comp import discover_heads
    from nomarr.components.ml.ml_inference_comp import make_predictor_uncached

    heads = discover_heads(models_dir)
    if not heads:
        logging.warning(f"[cache] No heads found in {models_dir}")
        return 0

    logging.info(f"[cache] Warming up predictor cache with {len(heads)} heads...")
    logging.info("[cache] Building model cache (Essentia warnings normal during warmup)...")
    start = time.time()

    # Note: Essentia's "No network created" warnings during model loading are expected
    # and harmless. They occur when TensorFlow graphs are loaded for the first time.
    # Once cached, subsequent predictions will be fast without warnings.

    for idx, head_info in enumerate(heads, 1):
        try:
            predictor = make_predictor_uncached(head_info)
            key = cache_key(head_info)
            _PREDICTOR_CACHE[key] = predictor
            logging.info(
                f"[cache] Cached [{idx}/{len(heads)}]: '{head_info.name}' ({head_info.backbone}/{head_info.head_type})"
            )
        except Exception as e:
            logging.error(f"[cache] Failed to cache predictor for {head_info.name}: {e}")

    elapsed = time.time() - start
    _CACHE_INITIALIZED = True
    _CACHE_LAST_ACCESS = time.time()
    logging.info(
        f"[cache] Predictor cache ready: {len(_PREDICTOR_CACHE)}/{len(heads)} predictors loaded in {elapsed:.1f}s"
    )
    if len(_PREDICTOR_CACHE) != len(heads):
        cached = set(_PREDICTOR_CACHE.keys())
        missing = [f"{h.name} ({h.backbone})" for h in heads if cache_key(h) not in cached]
        logging.warning(f"[cache] Missing from cache after warmup: {missing}")
    return len(_PREDICTOR_CACHE)


def clear_predictor_cache() -> int:
    """
    Clear the predictor cache and free GPU memory.
    Returns the number of predictors that were cleared.
    """
    global _PREDICTOR_CACHE, _CACHE_INITIALIZED, _CACHE_LAST_ACCESS

    with _CACHE_LOCK:
        count = len(_PREDICTOR_CACHE)
        _PREDICTOR_CACHE.clear()
        _CACHE_INITIALIZED = False
        _CACHE_LAST_ACCESS = 0.0

        # Force garbage collection and GPU memory cleanup
        import gc

        gc.collect()

        try:
            import tensorflow as tf

            tf.keras.backend.clear_session()
            logging.info("[cache] TensorFlow session cleared")
        except Exception as e:
            logging.warning(f"[cache] Could not clear TensorFlow session: {e}")

        logging.info(f"[cache] Cleared predictor cache ({count} predictors removed, GPU memory freed)")
        return count


def touch_cache() -> None:
    """Update the last access time for the cache."""
    global _CACHE_LAST_ACCESS
    _CACHE_LAST_ACCESS = time.time()


def get_cache_idle_time() -> float:
    """Get the number of seconds since last cache access."""
    return time.time() - _CACHE_LAST_ACCESS


def check_and_evict_idle_cache() -> bool:
    """
    Check if cache has been idle longer than timeout and evict if needed.
    Returns True if cache was evicted, False otherwise.

    If _CACHE_TIMEOUT is 0, cache is never evicted.
    """
    if _CACHE_TIMEOUT == 0:
        return False

    if not _CACHE_INITIALIZED or len(_PREDICTOR_CACHE) == 0:
        return False

    idle_time = get_cache_idle_time()
    if idle_time > _CACHE_TIMEOUT:
        logging.info(f"[cache] Cache idle for {idle_time:.0f}s (>{_CACHE_TIMEOUT}s), evicting...")
        clear_predictor_cache()
        return True

    return False
