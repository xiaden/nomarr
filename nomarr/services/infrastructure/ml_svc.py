"""ML Service: Manages ML model discovery and cache lifecycle.

This service owns ML model discovery, cache lifecycle, and provides a clean
interface for model operations without exposing component details to interfaces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from nomarr.components.ml.ml_cache_comp import get_cache_size, warmup_predictor_cache
from nomarr.components.ml.ml_discovery_comp import discover_backbones, discover_heads

logger = logging.getLogger(__name__)


@dataclass
class MLConfig:
    """Configuration for MLService."""

    models_dir: str
    cache_idle_timeout: int


class MLService:
    """Service for ML model discovery and cache management.

    Provides a clean interface for:
    - Discovering available backbones (embedding extractors)
    - Discovering model heads (classifiers)
    - Cache warmup and monitoring
    """

    def __init__(self, cfg: MLConfig) -> None:
        """Initialize ML service.

        Args:
            cfg: ML configuration

        """
        self.cfg = cfg

    def warmup_cache(self) -> int:
        """Pre-load all model predictors into cache.

        Returns:
            Number of predictors cached

        Raises:
            RuntimeError: If cache warmup fails

        """
        try:
            count = warmup_predictor_cache(
                models_dir=self.cfg.models_dir,
                cache_idle_timeout=self.cfg.cache_idle_timeout,
            )
            logger.info(f"[MLService] Warmed up {count} predictors")
            return count
        except Exception as e:
            logger.exception("[MLService] Cache warmup failed")
            msg = f"Failed to warm up ML cache: {e}"
            raise RuntimeError(msg) from e

    def get_cache_size(self) -> int:
        """Get number of predictors currently in cache.

        Returns:
            Number of cached predictors

        """
        return get_cache_size()

    def list_backbones(self) -> list[str]:
        """List available embedding backbones.

        Discovers backbones from models directory structure.
        A backbone is valid if it has embeddings/*.pb files.

        Returns:
            Sorted list of backbone identifiers (e.g., ["effnet", "musicnn"])

        """
        return discover_backbones(self.cfg.models_dir)

    def discover_heads(self) -> list[Any]:
        """Discover all available model heads in models directory.

        Returns:
            List of HeadInfo objects describing available models

        Raises:
            RuntimeError: If model discovery fails

        """
        try:
            heads = discover_heads(self.cfg.models_dir)
            logger.info(f"[MLService] Discovered {len(heads)} model heads")
            return heads
        except Exception as e:
            logger.exception("[MLService] Model discovery failed")
            msg = f"Failed to discover model heads: {e}"
            raise RuntimeError(msg) from e
