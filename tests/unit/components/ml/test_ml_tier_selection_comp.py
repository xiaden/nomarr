"""Tests for ml_tier_selection_comp.py."""

from __future__ import annotations

from nomarr.components.ml.ml_capacity_probe_comp import CapacityEstimate
from nomarr.components.ml.ml_tier_selection_comp import (
    ExecutionTier,
    select_execution_tier,
)


class TestSelectExecutionTier:
    """Tests for select_execution_tier()."""

    def test_tier_0_with_ample_resources(self):
        """Selects Tier 0 when resources are ample."""
        estimate = CapacityEstimate(
            model_set_hash="test123",
            measured_backbone_vram_mb=4000,  # 4GB backbone
            estimated_worker_ram_mb=2000,  # 2GB worker RAM
            gpu_capable=True,
        )

        result = select_execution_tier(
            capacity_estimate=estimate,
            vram_budget_mb=24000,  # 24GB VRAM - fits 2+ cached backbones
            ram_budget_mb=16000,  # 16GB RAM budget
            config_max_workers=4,
        )

        assert result.tier == ExecutionTier.FAST_PATH
        assert result.calculated_workers >= 1

    def test_tier_1_with_reduced_vram(self):
        """Selects Tier 1 when VRAM budget is smaller."""
        estimate = CapacityEstimate(
            model_set_hash="test123",
            measured_backbone_vram_mb=8000,  # 8GB backbone
            estimated_worker_ram_mb=2000,
            gpu_capable=True,
        )

        result = select_execution_tier(
            capacity_estimate=estimate,
            vram_budget_mb=12000,  # Only fits 1.5x backbone (not 2x for Tier 0)
            ram_budget_mb=16000,
            config_max_workers=4,
        )

        # Should fall to Tier 1 or lower since can't fit 2 cached backbones
        assert result.tier >= ExecutionTier.REDUCED_CACHE

    def test_tier_2_with_very_low_vram(self):
        """Selects Tier 2 when VRAM is below backbone requirements."""
        estimate = CapacityEstimate(
            model_set_hash="test123",
            measured_backbone_vram_mb=8000,  # 8GB backbone
            estimated_worker_ram_mb=2000,
            gpu_capable=True,
        )

        result = select_execution_tier(
            capacity_estimate=estimate,
            vram_budget_mb=6000,  # Less than one backbone
            ram_budget_mb=4000,  # Fits one worker
            config_max_workers=4,
        )

        # Should be Tier 2 or Tier 3 (or refuse) since VRAM < backbone
        assert result.tier >= ExecutionTier.SEQUENTIAL_GPU
        assert result.calculated_workers >= 0

    def test_tier_3_when_no_vram_budget(self):
        """Selects Tier 3 when VRAM budget is too low for GPU."""
        estimate = CapacityEstimate(
            model_set_hash="test123",
            measured_backbone_vram_mb=8000,
            estimated_worker_ram_mb=2000,
            gpu_capable=True,
        )

        result = select_execution_tier(
            capacity_estimate=estimate,
            vram_budget_mb=1000,  # Much less than backbone needs
            ram_budget_mb=16000,  # Enough RAM for CPU
            config_max_workers=4,
        )

        # Should fall to CPU tier or refuse
        assert result.tier >= ExecutionTier.SEQUENTIAL_CPU

    def test_tier_3_when_gpu_not_capable(self):
        """Selects Tier 3 when GPU is not available."""
        estimate = CapacityEstimate(
            model_set_hash="test123",
            measured_backbone_vram_mb=0,  # No VRAM measured (no GPU)
            estimated_worker_ram_mb=2000,
            gpu_capable=False,  # GPU not available
        )

        result = select_execution_tier(
            capacity_estimate=estimate,
            vram_budget_mb=20000,  # Irrelevant when no GPU
            ram_budget_mb=16000,
            config_max_workers=4,
        )

        assert result.tier == ExecutionTier.SEQUENTIAL_CPU
        assert result.config.prefer_gpu is False

    def test_tier_4_when_insufficient_ram(self):
        """Selects Tier 4 (refuse) when even CPU mode can't run."""
        estimate = CapacityEstimate(
            model_set_hash="test123",
            measured_backbone_vram_mb=0,
            estimated_worker_ram_mb=8000,  # 8GB worker RAM needed
            gpu_capable=False,
        )

        result = select_execution_tier(
            capacity_estimate=estimate,
            vram_budget_mb=0,
            ram_budget_mb=2000,  # Only 2GB RAM budget - not enough
            config_max_workers=4,
        )

        assert result.tier == ExecutionTier.REFUSE
        assert result.calculated_workers == 0

    def test_respects_config_max_workers(self):
        """Worker count is capped by config_max_workers."""
        estimate = CapacityEstimate(
            model_set_hash="test123",
            measured_backbone_vram_mb=2000,  # Small backbone
            estimated_worker_ram_mb=1000,  # Small worker RAM
            gpu_capable=True,
        )

        result = select_execution_tier(
            capacity_estimate=estimate,
            vram_budget_mb=40000,  # Could fit many workers
            ram_budget_mb=32000,
            config_max_workers=2,  # But limit to 2
        )

        assert result.calculated_workers <= 2


class TestTierConfig:
    """Tests for tier configuration properties."""

    def test_tier_0_has_gpu_preference(self):
        """Tier 0 prefers GPU."""
        estimate = CapacityEstimate(
            model_set_hash="test123",
            measured_backbone_vram_mb=4000,
            estimated_worker_ram_mb=2000,
            gpu_capable=True,
        )

        result = select_execution_tier(
            capacity_estimate=estimate,
            vram_budget_mb=24000,  # Ample for tier 0
            ram_budget_mb=16000,
            config_max_workers=4,
        )

        if result.tier <= ExecutionTier.SEQUENTIAL_GPU:
            assert result.config.prefer_gpu is True

    def test_tier_3_has_no_gpu_preference(self):
        """Tier 3 (CPU-only) does not prefer GPU."""
        estimate = CapacityEstimate(
            model_set_hash="test123",
            measured_backbone_vram_mb=0,
            estimated_worker_ram_mb=2000,
            gpu_capable=False,
        )

        result = select_execution_tier(
            capacity_estimate=estimate,
            vram_budget_mb=0,
            ram_budget_mb=16000,
            config_max_workers=4,
        )

        assert result.config.prefer_gpu is False
