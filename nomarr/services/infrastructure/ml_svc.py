"""ML Service: Model discovery facade.

This service provides a clean interface for discovering available models
without exposing component details to interfaces.  Cache lifecycle is
owned by DiscoveryWorker, not this service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from nomarr.components.ml.onnx.ml_discovery_comp import (
    discover_backbones,
    discover_heads,
)
from nomarr.components.ml.onnx.ml_model_registry_comp import (
    list_model_outputs_for_model,
    list_registered_models,
    mark_model_fully_configured,
    update_model_output_label,
)
from nomarr.components.ml.resources.ml_vram_probe_comp import clear_model_vram_measurements
from nomarr.helpers.dto.ml_head_dto import HeadInfo
from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


@dataclass
class MLConfig:
    """Configuration for MLService."""

    models_dir: str


class MLService:
    """ML model discovery facade.

    Provides a clean interface for:
    - Discovering available backbones (embedding extractors)
    - Discovering model heads (classifiers)

    Cache lifecycle is owned by DiscoveryWorker, not this service.
    """

    def __init__(self, db: Database, cfg: MLConfig) -> None:
        """Initialize ML service.

        Args:
            db: Database instance.
            cfg: ML configuration

        """
        self.db = db
        self.cfg = cfg

    def list_backbones(self) -> list[str]:
        """List available embedding backbones.

        Discovers backbones from models directory structure.
        A backbone is valid if it has embeddings/*.pb files.

        Returns:
            Sorted list of backbone identifiers (e.g., ["effnet", "musicnn"])

        """
        return discover_backbones(self.cfg.models_dir)

    async def discover_heads(self) -> list[HeadInfo]:
        """Discover all available model heads in models directory.

        Only returns heads whose corresponding ``ml_models`` entry is
        ``fully_configured=True``.  Unconfigured models are logged as
        warnings and excluded from inference.

        Returns:
            List of HeadInfo objects describing available models

        Raises:
            RuntimeError: If model discovery fails

        """
        try:
            raw_heads = await discover_heads(self.cfg.models_dir, self.db)
            logger.info("[MLService] Discovered %d model heads", len(raw_heads))
            # Convert component-level HeadInfo to DTO HeadInfo
            return [
                HeadInfo(
                    name=h.name,
                    labels=h.labels,
                    backbone=h.backbone,
                    head_type=h.head_type,
                    model_stem=h.model_stem,
                    model_path=h.model_path,
                    embedding_graph=h.embedding_graph,
                    is_regression_head=h.is_regression_head,
                )
                for h in raw_heads
            ]
        except Exception as e:
            logger.exception("[MLService] Model discovery failed")
            msg = f"Failed to discover model heads: {e}"
            raise RuntimeError(msg) from e

    def clear_vram_measurements(self) -> None:
        """Delete all per-model VRAM measurements from meta.

        The next discovery worker startup will re-run the probe and record
        fresh measurements.
        """
        clear_model_vram_measurements(self.db)
        logger.info("[MLService] VRAM measurements cleared — probe will re-run on next worker start")

    def list_all_models(self) -> list[dict[str, Any]]:
        """Return all registered ML model vertices.

        Returns:
            List of ml_models documents.

        """
        return list_registered_models(self.db)

    def get_model_outputs(self, model_id: str) -> list[dict[str, Any]]:
        """Return output vertices for a specific model.

        Args:
            model_id: Primary key of the model row.

        Returns:
            List of ml_model_outputs documents ordered by output_index.

        """
        return list_model_outputs_for_model(self.db, model_id)

    def update_output_label(self, model_id: int, output_id: int, label: str) -> None:
        """Write a human-readable label for a model output vertex.

        Args:
            model_id: Primary key of the parent model row.
            output_id: Primary key of the output row.
            label: Human-readable tag label for this activation.

        """
        update_model_output_label(self.db, model_id=model_id, output_id=output_id, label=label)

    def mark_model_configured(self, model_id: int, value: bool) -> None:
        """Set the fully_configured flag on a model vertex.

        Args:
            model_id: Primary key of the model row.
            value: True to enable model for inference, False to disable.

        """
        mark_model_fully_configured(self.db, model_id, value)
