"""Mixin for GPU capability checks and admission control."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.resources.ml_capacity_probe_comp import (
    CapacityEstimate,
    get_or_run_capacity_probe,
)
from nomarr.components.ml.resources.ml_tier_selection_comp import (
    TIER_CONFIGS,
    ExecutionTier,
    TierSelection,
    select_execution_tier,
)
from nomarr.components.platform.resource_monitor_comp import check_nvidia_gpu_capability

if TYPE_CHECKING:
    from nomarr.helpers.dto.processing_dto import ProcessorConfig
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


class GpuAdmissionOpsMixin:
    """Mixin for GPU capability checks and resource admission control.

    Requires the host class to provide:
    - ``self.db`` (Database)
    - ``self.processor_config`` (ProcessorConfig)
    - ``self.worker_count`` (int)
    - ``self._gpu_capable`` (bool | None)
    - ``self._capacity_estimate`` (CapacityEstimate | None)
    - ``self._tier_selection`` (TierSelection | None)
    """

    db: Database
    processor_config: ProcessorConfig
    worker_count: int
    _gpu_capable: bool | None
    _capacity_estimate: CapacityEstimate | None
    _tier_selection: TierSelection | None

    def _check_gpu_capability(self) -> bool:
        if self._gpu_capable is None:
            self._gpu_capable = check_nvidia_gpu_capability()
            if self._gpu_capable:
                logger.info("[WorkerSystemService] GPU capability confirmed")
            else:
                logger.info("[WorkerSystemService] GPU not available, running CPU-only")
        return self._gpu_capable

    def _run_admission_control(self) -> TierSelection:
        """Determine execution tier and worker count."""
        rm_config = self.processor_config.resource_management
        if rm_config is None or not rm_config.enabled:
            logger.debug("[WorkerSystemService] Resource management disabled, using configured worker count")
            self._tier_selection = TierSelection(
                tier=ExecutionTier.FAST_PATH,
                config=TIER_CONFIGS[ExecutionTier.FAST_PATH],
                calculated_workers=self.worker_count,
                reason="Resource management disabled",
            )
            return self._tier_selection
        self._check_gpu_capability()
        logger.info("[WorkerSystemService] Running capacity probe...")
        capacity_estimate = get_or_run_capacity_probe(
            db=self.db,
            models_dir=self.processor_config.models_dir,
            worker_id="worker_system_service",
            ram_detection_mode=rm_config.ram_detection_mode,
        )
        self._capacity_estimate = capacity_estimate
        if capacity_estimate.is_conservative:
            logger.warning("[WorkerSystemService] Using conservative capacity estimates (probe failed or timed out)")
        tier_selection = select_execution_tier(
            capacity_estimate=capacity_estimate,
            vram_budget_mb=rm_config.vram_budget_mb,
            ram_budget_mb=rm_config.ram_budget_mb,
            config_max_workers=self.worker_count,
        )
        self._tier_selection = tier_selection
        logger.info(
            "[WorkerSystemService] Tier selection: %s (workers=%d)",
            tier_selection.reason,
            tier_selection.calculated_workers,
        )
        return tier_selection
