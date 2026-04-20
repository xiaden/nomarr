"""Ml package."""

from .audio.ml_audio_comp import (
    AudioLoadCrashError,
    AudioLoadShutdownError,
    load_audio_mono,
    set_stop_event,
    should_skip_short,
    shutdown_audio_loader,
)
from .calibration.ml_calibration_comp import apply_minmax_calibration, save_calibration_sidecars
from .onnx.ml_discovery_comp import compute_model_suite_hash
from .resources.ml_capacity_probe_comp import (
    CapacityEstimate,
    compute_model_set_hash,
    get_or_run_capacity_probe,
    invalidate_capacity_estimate,
)
from .resources.ml_tier_selection_comp import (
    ExecutionTier,
    TierConfig,
    TierSelection,
    select_execution_tier,
)
from .resources.ml_vram_oom_helper_comp import (
    parse_oom_requested_bytes,
    update_model_vram_from_oom,
)

__all__ = [
    "AudioLoadCrashError",
    "AudioLoadShutdownError",
    "CapacityEstimate",
    "ExecutionTier",
    "TierConfig",
    "TierSelection",
    "apply_minmax_calibration",
    "compute_model_set_hash",
    "compute_model_suite_hash",
    "get_or_run_capacity_probe",
    "invalidate_capacity_estimate",
    "load_audio_mono",
    "parse_oom_requested_bytes",
    "save_calibration_sidecars",
    "select_execution_tier",
    "set_stop_event",
    "should_skip_short",
    "shutdown_audio_loader",
    "update_model_vram_from_oom",
]
