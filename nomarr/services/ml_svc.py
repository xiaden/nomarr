"""
ML Service: Manages ML model cache and predictor operations.

This service owns ML cache lifecycle and provides a clean interface for
warming up predictors without exposing ml layer details to interfaces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.admin_dto import CacheRefreshResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class MLConfig:
    """Configuration for MLService."""

    models_dir: str
    cache_idle_timeout: int


class MLService:
    """
    Service for managing ML model cache and predictor operations.

    Provides a clean interface for cache warmup without requiring
    interfaces to import from nomarr.components.ml directly.
    """

    def __init__(self, cfg: MLConfig):
        """
        Initialize ML service.

        Args:
            cfg: ML configuration
        """
        self.cfg = cfg

    def warmup_cache(self) -> int:
        """
        Pre-load all model predictors into cache.

        Returns:
            Number of predictors cached

        Raises:
            RuntimeError: If cache warmup fails
        """
        from nomarr.components.ml.ml_cache_comp import warmup_predictor_cache

        try:
            count = warmup_predictor_cache(
                models_dir=self.cfg.models_dir,
                cache_idle_timeout=self.cfg.cache_idle_timeout,
            )
            logger.info(f"[MLService] Warmed up {count} predictors")
            return count
        except Exception as e:
            logger.exception("[MLService] Cache warmup failed")
            raise RuntimeError(f"Failed to warm up ML cache: {e}") from e

    def warmup_cache_for_admin(self) -> CacheRefreshResult:
        """
        Pre-load all model predictors into cache for admin operations.

        Returns:
            CacheRefreshResult with status and message

        Raises:
            RuntimeError: If cache warmup fails
        """
        num = self.warmup_cache()
        return CacheRefreshResult(
            status="success",
            message=f"Cache refreshed ({num} predictors)",
        )

    def get_cache_size(self) -> int:
        """
        Get number of predictors currently in cache.

        Returns:
            Number of cached predictors
        """
        from nomarr.components.ml.ml_cache_comp import get_cache_size

        return get_cache_size()

    def discover_heads(self) -> list[Any]:
        """
        Discover all available model heads in models directory.

        Returns:
            List of HeadInfo objects describing available models

        Raises:
            RuntimeError: If model discovery fails
        """
        from nomarr.components.ml.ml_discovery_comp import discover_heads

        try:
            heads = discover_heads(self.cfg.models_dir)
            logger.info(f"[MLService] Discovered {len(heads)} model heads")
            return heads
        except Exception as e:
            logger.exception("[MLService] Model discovery failed")
            raise RuntimeError(f"Failed to discover model heads: {e}") from e
