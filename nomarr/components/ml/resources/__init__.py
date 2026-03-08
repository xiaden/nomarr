"""VRAM coordination, capacity probing, timing, tier selection."""

from .ml_capacity_probe_comp import (
    CapacityEstimate,
    compute_model_set_hash,
    get_or_run_capacity_probe,
    invalidate_capacity_estimate,
)
from .ml_tier_selection_comp import (
    ExecutionTier,
    TierConfig,
    TierSelection,
    select_execution_tier,
)
from .ml_vram_probe_comp import (
    parse_oom_requested_bytes,
    update_model_vram_from_oom,
)

__all__ = [
    "CapacityEstimate",
    "ExecutionTier",
    "TierConfig",
    "TierSelection",
    "compute_model_set_hash",
    "get_or_run_capacity_probe",
    "invalidate_capacity_estimate",
    "parse_oom_requested_bytes",
    "select_execution_tier",
    "update_model_vram_from_oom",
]
