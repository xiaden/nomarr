"""Predictor cache management for TensorFlow models.

Manages global caches of model predictors to avoid repeated model loading overhead.
Supports automatic cache eviction after idle timeout to free GPU memory.

Two cache tiers (both warmed at startup, both evicted together):
1. Head-only cache: TensorflowPredict2D objects (embedding → predictions)
2. Backbone cache: Embedding-only predictors (waveform → embeddings)

Each cache entry tracks its device placement ("cpu" or "gpu") via ``CachedPredictor``.
Per-item eviction supports device transitions without clearing the entire cache.

Eviction is state-driven, not timestamp-driven:
- ``mark_active()`` signals that a worker is using the cache (processing a file).
- ``mark_idle()``   signals that the worker finished and is polling for work.
- Eviction can only happen in the *idle* state, after the configured timeout elapses.
  This guarantees the cache is never cleared while a worker is mid-processing.
"""

from __future__ import annotations

import enum
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from nomarr.helpers.time_helper import internal_ms

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.components.ml.ml_discovery_comp import HeadInfo


# ---------------------------------------------------------------------------
# Device placement
# ---------------------------------------------------------------------------

DevicePlacement = Literal["cpu", "gpu"]
"""Device placement for a cached predictor. Mirrors Essentia C++ values."""


@dataclass(slots=True)
class CachedPredictor:
    """Wrapper for a cached predictor with device tracking."""

    predictor: Any
    device: DevicePlacement


# ---------------------------------------------------------------------------
# Cache lifecycle state
# ---------------------------------------------------------------------------


class CacheState(enum.Enum):
    """Cache lifecycle states."""

    IDLE = "idle"
    ACTIVE = "active"


_HEAD_ONLY_CACHE: dict[str, CachedPredictor] = {}  # head-only TensorflowPredict2D objects
_BACKBONE_CACHE: dict[str, CachedPredictor] = {}  # backbone embedding predictors
_CACHE_INITIALIZED = False
_CACHE_STATE: CacheState = CacheState.IDLE
_CACHE_IDLE_SINCE: int = 0  # ms timestamp when state last became IDLE
_CACHE_LOCK = threading.Lock()
_CACHE_TIMEOUT: int = 40  # Default idle timeout in seconds


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def cache_key(head_info: HeadInfo) -> str:
    """Unique cache key for a head across backbones/types."""
    return f"{head_info.name}::{head_info.backbone}::{head_info.head_type}"


def backbone_cache_key(backbone: str, emb_graph: str) -> str:
    """Generate cache key for a backbone embedding predictor."""
    return f"backbone::{backbone}::{emb_graph}"


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def is_initialized() -> bool:
    """Check if cache has been initialized."""
    return _CACHE_INITIALIZED


def get_cache_size() -> int:
    """Return total number of predictors in cache (heads + backbones)."""
    return len(_HEAD_ONLY_CACHE) + len(_BACKBONE_CACHE)


def get_backbone_cache_size() -> int:
    """Return number of backbone predictors in cache."""
    return len(_BACKBONE_CACHE)


def get_head_only_cache_size() -> int:
    """Return number of head-only predictors in cache."""
    return len(_HEAD_ONLY_CACHE)


# ---------------------------------------------------------------------------
# Head-only predictor cache
# ---------------------------------------------------------------------------


def get_cached_head_predictor(head_info: HeadInfo) -> Any | None:
    """Get cached head-only predictor if available.

    Returns the raw predictor object (transparent unwrapping).
    """
    key = cache_key(head_info)
    entry = _HEAD_ONLY_CACHE.get(key)
    return entry.predictor if entry is not None else None


def get_cached_head_device(head_info: HeadInfo) -> DevicePlacement | None:
    """Get device placement of a cached head predictor.

    Returns None if not cached.
    """
    key = cache_key(head_info)
    entry = _HEAD_ONLY_CACHE.get(key)
    return entry.device if entry is not None else None


def cache_head_predictor(head_info: HeadInfo, predictor: Any, device: DevicePlacement = "cpu") -> None:
    """Cache a head-only TensorflowPredict2D predictor for reuse."""
    key = cache_key(head_info)
    with _CACHE_LOCK:
        _HEAD_ONLY_CACHE[key] = CachedPredictor(predictor=predictor, device=device)
        logger.debug(f"[cache] Cached head-only predictor: {head_info.name} (device={device})")


def evict_head_predictor(head_info: HeadInfo) -> bool:
    """Evict a single head predictor from cache.

    Used for device transitions (evict old device, recreate on new device).
    Returns True if an entry was evicted, False if key was absent.
    """
    key = cache_key(head_info)
    with _CACHE_LOCK:
        entry = _HEAD_ONLY_CACHE.pop(key, None)
    if entry is not None:
        logger.debug(f"[cache] Evicted head predictor: {head_info.name} (was device={entry.device})")
        del entry
        return True
    return False


# ---------------------------------------------------------------------------
# Backbone predictor cache
# ---------------------------------------------------------------------------


def get_cached_backbone_predictor(backbone: str, emb_graph: str) -> Any | None:
    """Get cached backbone predictor if available.

    Returns the raw predictor object (transparent unwrapping).
    """
    key = backbone_cache_key(backbone, emb_graph)
    entry = _BACKBONE_CACHE.get(key)
    return entry.predictor if entry is not None else None


def get_cached_backbone_device(backbone: str, emb_graph: str) -> DevicePlacement | None:
    """Get device placement of a cached backbone predictor.

    Returns None if not cached.
    """
    key = backbone_cache_key(backbone, emb_graph)
    entry = _BACKBONE_CACHE.get(key)
    return entry.device if entry is not None else None


def cache_backbone_predictor(backbone: str, emb_graph: str, predictor: Any, device: DevicePlacement = "gpu") -> None:
    """Cache a backbone predictor for reuse."""
    key = backbone_cache_key(backbone, emb_graph)
    with _CACHE_LOCK:
        _BACKBONE_CACHE[key] = CachedPredictor(predictor=predictor, device=device)
        logger.debug(f"[cache] Cached backbone predictor: {backbone} (device={device})")


def evict_backbone_predictor(backbone: str, emb_graph: str) -> bool:
    """Evict a single backbone predictor from cache.

    Used for device transitions (evict old device, recreate on new device).
    Returns True if an entry was evicted, False if key was absent.
    """
    key = backbone_cache_key(backbone, emb_graph)
    with _CACHE_LOCK:
        entry = _BACKBONE_CACHE.pop(key, None)
    if entry is not None:
        logger.debug(f"[cache] Evicted backbone predictor: {backbone} (was device={entry.device})")
        del entry
        return True
    return False


# ---------------------------------------------------------------------------
# Warmup / eviction (applies to ALL caches)
# ---------------------------------------------------------------------------


def warmup_predictor_cache(models_dir: str, cache_idle_timeout: int = 40) -> int:
    """Pre-load all model predictors into cache to avoid loading overhead during processing.
    Returns the total number of predictors cached.

    Warms both tiers:
    1. Head-only predictors (TensorflowPredict2D, embedding -> head) on CPU
    2. Backbone predictors (embedding-only, waveform -> embeddings) on GPU

    Backbone graphs are derived from discovered heads (each HeadInfo knows its
    backbone name + embedding_graph path), so no separate backbone discovery needed.

    Args:
        models_dir: Directory containing model files
        cache_idle_timeout: Seconds before idle cache eviction (0 = never evict, default: 40)

    """
    global _CACHE_INITIALIZED, _CACHE_IDLE_SINCE, _CACHE_TIMEOUT
    _CACHE_TIMEOUT = cache_idle_timeout
    if _CACHE_INITIALIZED:
        logger.info("[cache] Predictor cache already initialized")
        return get_cache_size()
    from nomarr.components.ml.ml_discovery_comp import discover_heads
    from nomarr.components.ml.ml_inference_comp import _create_backbone_predictor, _create_head_only_predictor

    heads = discover_heads(models_dir)
    if not heads:
        logger.warning(f"[cache] No heads found in {models_dir}")
        return 0
    logger.info(f"[cache] Warming up predictor cache with {len(heads)} heads...")
    logger.info("[cache] Building model cache (Essentia warnings normal during warmup)...")
    start = internal_ms()

    # 1. Head-only predictors (default: CPU)
    head_cached = 0
    for idx, head_info in enumerate(heads, 1):
        try:
            key = cache_key(head_info)
            if key not in _HEAD_ONLY_CACHE:
                predictor = _create_head_only_predictor(head_info, device_placement="cpu")
                _HEAD_ONLY_CACHE[key] = CachedPredictor(predictor=predictor, device="cpu")
                head_cached += 1
            logger.debug(
                f"[cache] Head [{idx}/{len(heads)}]: '{head_info.name}' ({head_info.backbone}/{head_info.head_type}) device=cpu"
            )
        except Exception as e:
            logger.exception(f"[cache] Failed to cache head predictor for {head_info.name}: {e}")

    # 2. Backbone predictors (default: GPU)
    backbone_cached = 0
    seen_backbones: set[str] = set()
    for head_info in heads:
        bb_key = backbone_cache_key(head_info.backbone, head_info.embedding_graph)
        if bb_key in seen_backbones:
            continue
        seen_backbones.add(bb_key)
        try:
            if bb_key not in _BACKBONE_CACHE:
                predictor = _create_backbone_predictor(head_info.backbone, head_info.embedding_graph, device_placement="gpu")
                _BACKBONE_CACHE[bb_key] = CachedPredictor(predictor=predictor, device="gpu")
                backbone_cached += 1
                logger.debug(f"[cache] Backbone: {head_info.backbone} device=gpu")
        except Exception as e:
            logger.exception(f"[cache] Failed to cache backbone predictor for {head_info.backbone}: {e}")

    elapsed = internal_ms().value - start.value
    _CACHE_INITIALIZED = True
    _CACHE_IDLE_SINCE = internal_ms().value
    total = get_cache_size()
    logger.info(
        f"[cache] Predictor cache ready: {head_cached} heads (cpu) + {backbone_cached} backbones (gpu) = {total} total in {elapsed:.0f}ms"
    )
    if len(_HEAD_ONLY_CACHE) != len(heads):
        cached = set(_HEAD_ONLY_CACHE.keys())
        missing = [f"{h.name} ({h.backbone})" for h in heads if cache_key(h) not in cached]
        logger.warning(f"[cache] Missing heads from cache after warmup: {missing}")
    return total


def clear_predictor_cache() -> int:
    """Clear all caches and free GPU memory.
    Returns the number of predictors that were cleared.
    """
    global _HEAD_ONLY_CACHE, _BACKBONE_CACHE, _CACHE_INITIALIZED, _CACHE_IDLE_SINCE, _CACHE_STATE
    with _CACHE_LOCK:
        count = len(_HEAD_ONLY_CACHE) + len(_BACKBONE_CACHE)
        _HEAD_ONLY_CACHE.clear()
        _BACKBONE_CACHE.clear()
        _CACHE_INITIALIZED = False
        _CACHE_IDLE_SINCE = 0
        _CACHE_STATE = CacheState.IDLE
        import gc

        gc.collect()
        logger.info(f"[cache] Cleared predictor cache ({count} predictors removed, GPU memory freed)")
        return count


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


def mark_active() -> None:
    """Signal that the cache is in active use (worker processing a file).

    While active, the idle-eviction check is a no-op.
    """
    global _CACHE_STATE
    _CACHE_STATE = CacheState.ACTIVE


def mark_idle() -> None:
    """Signal that the cache is no longer in active use.

    Starts (or restarts) the idle timer used by ``check_and_evict_idle_cache``.
    """
    global _CACHE_STATE, _CACHE_IDLE_SINCE
    _CACHE_STATE = CacheState.IDLE
    _CACHE_IDLE_SINCE = internal_ms().value


def get_cache_state() -> CacheState:
    """Return the current cache state."""
    return _CACHE_STATE


def get_cache_idle_time() -> float:
    """Get the number of seconds since cache entered the idle state.

    Returns 0.0 if the cache is currently active.
    """
    if _CACHE_STATE is CacheState.ACTIVE:
        return 0.0
    return (internal_ms().value - _CACHE_IDLE_SINCE) / 1000


def check_and_evict_idle_cache() -> bool:
    """Check if cache has been idle longer than timeout and evict if needed.
    Returns True if cache was evicted, False otherwise.

    Eviction is blocked while the cache state is ACTIVE.
    If _CACHE_TIMEOUT is 0, cache is never evicted.
    """
    if _CACHE_TIMEOUT == 0:
        return False
    if _CACHE_STATE is CacheState.ACTIVE:
        return False
    if not _CACHE_INITIALIZED or get_cache_size() == 0:
        return False
    idle_time = get_cache_idle_time()
    if idle_time > _CACHE_TIMEOUT:
        logger.info(f"[cache] Cache idle for {idle_time:.0f}s (>{_CACHE_TIMEOUT}s), evicting...")
        clear_predictor_cache()
        return True
    return False
