"""Execution Tier Selection for GPU/CPU adaptive resource management.

Implements the tier ladder per GPU_REFACTOR_PLAN.md Section 8-9:
- Tier 0: Fast Path (cached, multi-worker, 2-3s/file)
- Tier 1: Reduced Cache (smaller caches, fewer workers, 3-5s/file)
- Tier 2: Sequential GPU (no cache, single worker, 5-10s/file)
- Tier 3: Sequential CPU (backbone on CPU, single worker, 30-60s/file)
- Tier 4: Refuse (insufficient resources)

Tier selection is deterministic and owned by WorkerSystemService.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.components.ml.ml_capacity_probe_comp import CapacityEstimate

logger = logging.getLogger(__name__)


class ExecutionTier(IntEnum):
    """ML execution tiers (higher = faster, more resource-intensive).

    Per GPU_REFACTOR_PLAN.md Section 8:
    - Tier 0: Fast Path - cached, multi-worker
    - Tier 1: Reduced Cache - smaller caches, fewer workers
    - Tier 2: Sequential GPU - no cache, single worker
    - Tier 3: Sequential CPU - backbone on CPU, single worker
    - Tier 4: Refuse - insufficient resources
    """

    FAST_PATH = 0
    REDUCED_CACHE = 1
    SEQUENTIAL_GPU = 2
    SEQUENTIAL_CPU = 3
    REFUSE = 4


@dataclass
class TierConfig:
    """Configuration for an execution tier.

    Attributes:
        tier: The execution tier
        max_workers: Maximum worker count for this tier
        backbone_cache_size: Number of backbones to cache (0 = no cache)
        head_cache_size: Number of heads to cache (0 = no cache)
        prefer_gpu: Whether to prefer GPU for backbone execution
        description: Human-readable description

    """

    tier: ExecutionTier
    max_workers: int
    backbone_cache_size: int
    head_cache_size: int
    prefer_gpu: bool
    description: str


# Tier configuration constants
# Per GPU_REFACTOR_PLAN.md Section 8

TIER_CONFIGS: dict[ExecutionTier, TierConfig] = {
    ExecutionTier.FAST_PATH: TierConfig(
        tier=ExecutionTier.FAST_PATH,
        max_workers=4,  # Will be calculated from budgets
        backbone_cache_size=2,  # ~12GB VRAM for 2 backbones
        head_cache_size=24,  # ~2GB RAM for 24 heads
        prefer_gpu=True,
        description="Fast Path: cached, multi-worker (2-3s/file)",
    ),
    ExecutionTier.REDUCED_CACHE: TierConfig(
        tier=ExecutionTier.REDUCED_CACHE,
        max_workers=2,  # Reduced from tier 0
        backbone_cache_size=1,  # ~8GB VRAM for 1 backbone
        head_cache_size=12,  # ~1GB RAM for 12 heads
        prefer_gpu=True,
        description="Reduced Cache: smaller caches, fewer workers (3-5s/file)",
    ),
    ExecutionTier.SEQUENTIAL_GPU: TierConfig(
        tier=ExecutionTier.SEQUENTIAL_GPU,
        max_workers=1,  # Single worker
        backbone_cache_size=0,  # No persistent cache
        head_cache_size=0,  # Load on demand
        prefer_gpu=True,
        description="Sequential GPU: no cache, single worker (5-10s/file)",
    ),
    ExecutionTier.SEQUENTIAL_CPU: TierConfig(
        tier=ExecutionTier.SEQUENTIAL_CPU,
        max_workers=1,  # Single worker
        backbone_cache_size=0,  # No cache
        head_cache_size=0,  # Load on demand
        prefer_gpu=False,  # Force CPU for backbone
        description="Sequential CPU: backbone on CPU, single worker (30-60s/file)",
    ),
    ExecutionTier.REFUSE: TierConfig(
        tier=ExecutionTier.REFUSE,
        max_workers=0,  # No workers
        backbone_cache_size=0,
        head_cache_size=0,
        prefer_gpu=False,
        description="Refuse: insufficient resources for any tier",
    ),
}

# Minimum RAM required for Tier 3 (CPU-only)
# One backbone + heads + Python overhead
MIN_RAM_FOR_CPU_ONLY_MB = 4096


@dataclass
class TierSelection:
    """Result of tier selection.

    Attributes:
        tier: Selected execution tier
        config: Configuration for the tier
        calculated_workers: Actual worker count (may differ from config.max_workers)
        reason: Why this tier was selected

    """

    tier: ExecutionTier
    config: TierConfig
    calculated_workers: int
    reason: str


def select_execution_tier(
    capacity_estimate: CapacityEstimate,
    vram_budget_mb: int,
    ram_budget_mb: int,
    config_max_workers: int,
) -> TierSelection:
    """Select the highest-performance tier that fits within resource budgets.

    Per GPU_REFACTOR_PLAN.md Section 9:
    - Tier selection is deterministic
    - Owned by WorkerSystemService (infrastructure layer)
    - If GPU not capable → skip Tiers 0-2
    - Select the highest tier whose requirements fit within budgets
    - Tier 4 means refusal, not retry

    Args:
        capacity_estimate: Resource measurements from ML capacity probe
        vram_budget_mb: User-configured VRAM budget in MB
        ram_budget_mb: User-configured RAM budget in MB
        config_max_workers: User-configured maximum worker count

    Returns:
        TierSelection with tier, config, and calculated worker count

    """
    gpu_capable = capacity_estimate.gpu_capable
    backbone_vram = capacity_estimate.measured_backbone_vram_mb
    worker_ram = capacity_estimate.estimated_worker_ram_mb

    # If GPU not capable, skip to Tier 3
    if not gpu_capable:
        logger.info("[tier_selection] GPU not available, checking CPU-only tier (Tier 3)")
        return _evaluate_cpu_only_tier(
            worker_ram=worker_ram,
            ram_budget_mb=ram_budget_mb,
            config_max_workers=config_max_workers,
        )

    # Try each tier from highest performance to lowest
    # Tier 0: Fast Path
    tier_0_result = _evaluate_tier_0(
        backbone_vram=backbone_vram,
        worker_ram=worker_ram,
        vram_budget_mb=vram_budget_mb,
        ram_budget_mb=ram_budget_mb,
        config_max_workers=config_max_workers,
    )
    if tier_0_result is not None:
        return tier_0_result

    # Tier 1: Reduced Cache
    tier_1_result = _evaluate_tier_1(
        backbone_vram=backbone_vram,
        worker_ram=worker_ram,
        vram_budget_mb=vram_budget_mb,
        ram_budget_mb=ram_budget_mb,
        config_max_workers=config_max_workers,
    )
    if tier_1_result is not None:
        return tier_1_result

    # Tier 2: Sequential GPU
    tier_2_result = _evaluate_tier_2(
        backbone_vram=backbone_vram,
        worker_ram=worker_ram,
        vram_budget_mb=vram_budget_mb,
        ram_budget_mb=ram_budget_mb,
    )
    if tier_2_result is not None:
        return tier_2_result

    # Tier 3: Sequential CPU (GPU not needed)
    return _evaluate_cpu_only_tier(
        worker_ram=worker_ram,
        ram_budget_mb=ram_budget_mb,
        config_max_workers=config_max_workers,
    )


def _evaluate_tier_0(
    backbone_vram: int,
    worker_ram: int,
    vram_budget_mb: int,
    ram_budget_mb: int,
    config_max_workers: int,
) -> TierSelection | None:
    """Evaluate Tier 0 (Fast Path) eligibility.

    Requirements:
    - VRAM budget >= 2 * backbone_vram (cache 2 backbones)
    - RAM budget >= worker_ram per worker

    Returns:
        TierSelection if eligible, None otherwise

    """
    tier_config = TIER_CONFIGS[ExecutionTier.FAST_PATH]

    # Calculate how many workers fit in VRAM (2 backbones cached)
    min_vram_for_tier = 2 * backbone_vram  # Need room for 2 cached backbones

    if vram_budget_mb < min_vram_for_tier:
        return None

    # Calculate workers that fit in budgets
    vram_workers = vram_budget_mb // (2 * backbone_vram) if backbone_vram > 0 else config_max_workers
    ram_workers = ram_budget_mb // worker_ram if worker_ram > 0 else config_max_workers

    calculated_workers = min(vram_workers, ram_workers, config_max_workers)

    if calculated_workers < 1:
        return None

    return TierSelection(
        tier=ExecutionTier.FAST_PATH,
        config=tier_config,
        calculated_workers=calculated_workers,
        reason=f"Tier 0: {calculated_workers} workers (vram={vram_budget_mb}MB, ram={ram_budget_mb}MB)",
    )


def _evaluate_tier_1(
    backbone_vram: int,
    worker_ram: int,
    vram_budget_mb: int,
    ram_budget_mb: int,
    config_max_workers: int,
) -> TierSelection | None:
    """Evaluate Tier 1 (Reduced Cache) eligibility.

    Requirements:
    - VRAM budget >= 1 * backbone_vram (cache 1 backbone)
    - RAM budget >= worker_ram per worker
    """
    tier_config = TIER_CONFIGS[ExecutionTier.REDUCED_CACHE]

    min_vram_for_tier = backbone_vram  # Need room for 1 cached backbone

    if vram_budget_mb < min_vram_for_tier:
        return None

    # Calculate workers that fit in budgets (max 2 for tier 1)
    vram_workers = vram_budget_mb // backbone_vram if backbone_vram > 0 else 2
    ram_workers = ram_budget_mb // worker_ram if worker_ram > 0 else 2

    calculated_workers = min(vram_workers, ram_workers, config_max_workers, tier_config.max_workers)

    if calculated_workers < 1:
        return None

    return TierSelection(
        tier=ExecutionTier.REDUCED_CACHE,
        config=tier_config,
        calculated_workers=calculated_workers,
        reason=f"Tier 1: {calculated_workers} workers (reduced cache)",
    )


def _evaluate_tier_2(
    backbone_vram: int,
    worker_ram: int,
    vram_budget_mb: int,
    ram_budget_mb: int,
) -> TierSelection | None:
    """Evaluate Tier 2 (Sequential GPU) eligibility.

    Requirements:
    - VRAM budget >= backbone_vram (for one backbone at a time)
    - RAM budget >= worker_ram (for one worker)
    """
    tier_config = TIER_CONFIGS[ExecutionTier.SEQUENTIAL_GPU]

    # Need room for one backbone in VRAM
    if vram_budget_mb < backbone_vram:
        return None

    # Need room for one worker in RAM
    if ram_budget_mb < worker_ram:
        return None

    return TierSelection(
        tier=ExecutionTier.SEQUENTIAL_GPU,
        config=tier_config,
        calculated_workers=1,
        reason="Tier 2: Sequential GPU (no cache, single worker)",
    )


def _evaluate_cpu_only_tier(
    worker_ram: int,
    ram_budget_mb: int,
    config_max_workers: int,
) -> TierSelection:
    """Evaluate Tier 3/4 (CPU-only) eligibility.

    Tier 3 requires:
    - RAM budget >= MIN_RAM_FOR_CPU_ONLY_MB (backbone + heads + overhead)

    If not met, returns Tier 4 (Refuse).
    """
    # CPU-only needs enough RAM for backbone + heads
    min_ram_needed = max(worker_ram, MIN_RAM_FOR_CPU_ONLY_MB)

    if ram_budget_mb >= min_ram_needed:
        tier_config = TIER_CONFIGS[ExecutionTier.SEQUENTIAL_CPU]
        return TierSelection(
            tier=ExecutionTier.SEQUENTIAL_CPU,
            config=tier_config,
            calculated_workers=1,
            reason="Tier 3: Sequential CPU (backbone on CPU, single worker)",
        )

    # Tier 4: Refuse - insufficient resources
    tier_config = TIER_CONFIGS[ExecutionTier.REFUSE]
    logger.error(
        "[tier_selection] Insufficient resources for any tier. "
        "RAM budget=%dMB, need at least %dMB for Tier 3 (CPU-only). "
        "Check config budgets or reduce model set.",
        ram_budget_mb,
        min_ram_needed,
    )
    return TierSelection(
        tier=ExecutionTier.REFUSE,
        config=tier_config,
        calculated_workers=0,
        reason=f"Tier 4: Refuse (need {min_ram_needed}MB RAM, have {ram_budget_mb}MB)",
    )


def get_tier_description(tier: ExecutionTier) -> str:
    """Get human-readable description for a tier."""
    return TIER_CONFIGS[tier].description
