"""Per-model VRAM probe component.

Measures the actual VRAM consumed by each ONNX model on the current GPU and stores
results in the ``meta`` collection as:

    ``ml_model_vram:{model_path}`` -> bytes (str), or ``str(sys.maxsize)`` if not measured

Design constraints:
- Models are probed sequentially — only one session live at a time.
- CUDA context is pre-warmed with a minimal identity model before any real
  measurement, so context overhead (~400-600 MB) is not attributed to the
  first backbone.
- Measurements are stored in bytes — same unit as ``gpu_mem_limit`` in
  the ONNX CUDAExecutionProvider options (Plan B consumer).
- ``sys.maxsize`` means the model was not measured (GPU unavailable, load failed,
  etc.) — the VRAM coordinator will naturally reject GPU placement for that model.
"""

from __future__ import annotations

import logging
import pathlib
import re
import sys

import numpy as np

from nomarr.components.ml.ml_discovery_comp import discover_backbone_models, discover_head_models_no_db
from nomarr.components.ml.ml_onnx_base import BaseONNXModel
from nomarr.components.platform.resource_monitor_comp import (
    get_vram_usage_mb,
    reset_telemetry_cache,
)
from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

# Meta key prefix for per-model VRAM measurements
_META_PREFIX = "ml_model_vram:"

# Regex to extract the requested byte count from a BFC arena OOM error message.
# ORT format: "BFCArena::AllocateRawInternal: Available memory of X is smaller than requested bytes of Y"
_OOM_PATTERN = re.compile(r"requested bytes of (\d+)")


def _fmt_bytes(n: int) -> str:
    """Format a byte count as a human-readable string (B / MB / GB)."""
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.2f} GB"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    return f"{n} B"


def parse_oom_requested_bytes(error: BaseException) -> int | None:
    """Parse the requested-bytes value from a BFC arena OOM error message.

    ORT raises ``RuntimeError`` with a message matching::

        BFCArena::AllocateRawInternal: Available memory of X is smaller
        than requested bytes of Y

    Args:
        error: The caught exception (any ``BaseException`` subclass).

    Returns:
        The integer byte count *Y* from the message, or ``None`` if the
        pattern is not present (i.e. not a BFC arena OOM).
    """
    match = _OOM_PATTERN.search(str(error))
    if match is None:
        return None
    return int(match.group(1))


def update_model_vram_from_oom(db: Database, model_path: str, requested_bytes: int) -> int:
    """Write a corrected VRAM limit after a BFC arena OOM.

    Bumps the *existing probe measurement* by 25% and persists it to
    ``meta[ml_model_vram:<model_path>]``.  The probe value is used as the
    baseline because it reflects the model's true total VRAM footprint;
    *requested_bytes* from the OOM message is only a single layer's
    activation allocation and is not representative of the whole model.

    If no probe value exists yet, falls back to ``requested_bytes * 1.25``
    as a best-effort estimate.

    Args:
        db:              Database instance.
        model_path:      Model path key (the part after the prefix).
        requested_bytes: Byte count parsed from the OOM message (used only
                         as fallback when no probe entry exists).

    Returns:
        The new VRAM limit in bytes.
    """
    raw = db.meta.get(f"{_META_PREFIX}{model_path}")
    base = int(raw) if raw is not None else requested_bytes
    new_limit = int(base * 1.25)
    db.meta.set(f"{_META_PREFIX}{model_path}", str(new_limit))
    logger.warning(
        "[vram_probe] OOM self-heal: updated %s from %s to %s (%d bytes) — bumped probe by 25%%",
        model_path,
        _fmt_bytes(base),
        _fmt_bytes(new_limit),
        new_limit,
    )
    return new_limit


# Pre-built minimal identity ONNX model for CUDA context warming.
# Generated via onnx/onnx-ecosystem image; no onnx package needed at runtime.
_WARMUP_FIXTURE_PATH: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "ml_cuda_warmup.onnx"
)


def _init_cuda_context() -> None:
    """Warm the CUDA context before any real model measurement.

    Loads the pre-built identity fixture on the GPU, runs one inference pass
    to trigger cuDNN initialisation, then immediately releases the session.
    VRAM charged to context setup (~400-600 MB) is not attributed to any
    backbone or head measurement.
    """
    import onnxruntime as ort  # local import — not installed in all environments

    if not _WARMUP_FIXTURE_PATH.exists():
        logger.warning(
            "[vram_probe] CUDA warmup fixture not found at %s — context overhead will "
            "inflate the first backbone measurement",
            _WARMUP_FIXTURE_PATH,
        )
        return

    try:
        opts = ort.SessionOptions()
        opts.log_severity_level = 3  # suppress verbose CUDA output
        sess = ort.InferenceSession(
            str(_WARMUP_FIXTURE_PATH),
            sess_options=opts,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        dummy = np.zeros((1, 16000), dtype=np.float32)
        sess.run(None, {"X": dummy})
        del sess
        logger.debug("[vram_probe] CUDA context warmed")
    except Exception:
        logger.warning("[vram_probe] CUDA context warming failed", exc_info=True)


def _probe_single_model(
    model: BaseONNXModel,
    probe_waveform: np.ndarray | None,
) -> int | None:
    """Measure peak VRAM consumed by one model on GPU (load + inference).

    ORT's BFC arena uses ``kNextPowerOfTwo`` strategy in probe mode (no
    ``gpu_mem_limit``), which means the arena grows on each extension but
    **never shrinks**.  After ``run()`` returns the arena still holds its peak
    allocation, so a single post-run nvidia-smi snapshot is the authoritative
    measurement.

    A background polling thread (50 ms interval) is kept as a safety net for
    load-phase allocations that happen before ``run()`` is called.

    Args:
        model: Unloaded ONNX model instance.
        probe_waveform: Float32 mono waveform for backbone models.  Pass
            ``None`` for head models — a synthetic zero embedding is generated
            from the model's ``input_dim`` after loading.

    Returns:
        Peak VRAM delta in bytes, or ``None`` if the model failed to load or run.
    """
    import threading

    _poll_interval_s = 0.05  # 50 ms — nvidia-smi updates ~100 ms, so this oversamples

    reset_telemetry_cache()
    before_mb = int(get_vram_usage_mb().get("used_mb", 0))
    peak_mb = before_mb

    stop_event = threading.Event()

    def _poll() -> None:
        nonlocal peak_mb
        while not stop_event.wait(_poll_interval_s):
            reset_telemetry_cache()
            current_mb = int(get_vram_usage_mb().get("used_mb", 0))
            if current_mb > peak_mb:
                peak_mb = current_mb

    poller = threading.Thread(target=_poll, daemon=True)
    poller.start()

    try:
        try:
            model.load("gpu")
        except Exception:
            logger.warning("[vram_probe] Failed to load %s on GPU", model._path, exc_info=True)
            return None

        # Detect silent ORT EP fallback to CPU (cudnn_frontend failure etc.)
        # session.get_providers() returns only CPUExecutionProvider when CUDA was rejected
        active_providers = model._session.get_providers() if model._session is not None else []
        if "CUDAExecutionProvider" not in active_providers:
            logger.warning(
                "[vram_probe] %s fell back to CPU (providers=%s) — storing sys.maxsize (coordinator will reject GPU)",
                model._path,
                active_providers,
            )
            model.unload()
            return None

        try:
            if probe_waveform is not None:
                # Backbone: run() handles mel-spectrogram preprocessing internally
                model.run(probe_waveform)
            else:
                # Head: input_dim is populated by load(); generate synthetic embeddings
                input_dim: int | None = getattr(model, "input_dim", None)
                if input_dim:
                    embeddings = np.zeros((10, input_dim), dtype=np.float32)
                    model.run(embeddings)
                else:
                    logger.warning(
                        "[vram_probe] Head %s has no input_dim after load — skipping run",
                        model._path,
                    )
        except Exception:
            logger.warning("[vram_probe] Inference failed for %s", model._path, exc_info=True)
            # Still capture the load-time VRAM even if run failed

        # Final sample after run so the poller catches any late arena growth
        reset_telemetry_cache()
        final_mb = int(get_vram_usage_mb().get("used_mb", 0))
        if final_mb > peak_mb:
            peak_mb = final_mb

    finally:
        stop_event.set()
        poller.join(timeout=2.0)

    model.unload()

    delta_bytes = (peak_mb - before_mb) * 1024 * 1024
    if delta_bytes < 0:
        logger.warning(
            "[vram_probe] Negative VRAM delta for %s (%d MB -> %d MB) — nvidia-smi may be stale",
            model._path,
            before_mb,
            peak_mb,
        )
        return None

    return delta_bytes


def probe_all_models(db: Database, models_dir: str) -> None:
    """Probe every backbone and head model and store VRAM measurements in meta.

    Runs sequentially: only one model is live on the GPU at a time.  Warms the
    CUDA context before the first real measurement.  Any model that fails to
    load or produces a negative delta is recorded as ``sys.maxsize``.

    Args:
        db: Database instance (used to write ``meta`` keys).
        models_dir: Root directory containing backbone sub-directories.
    """
    backbones = discover_backbone_models(models_dir)
    heads = discover_head_models_no_db(models_dir)

    n_backbones = len(backbones)
    n_heads = len(heads)
    logger.debug("[vram_probe] Probing %d backbone(s) and %d head(s)", n_backbones, n_heads)

    vram_info = get_vram_usage_mb()
    available_mb = int(vram_info.get("total_mb", 0)) - int(vram_info.get("used_mb", 0))
    logger.debug("[vram_probe] Available VRAM: %d MB — probing without limits", available_mb)

    _init_cuda_context()

    # Generate synthetic probe waveform — long enough for a full backbone batch
    probe_waveform = _make_probe_waveform()

    all_models: list[tuple[BaseONNXModel, np.ndarray | None]] = [
        (m, probe_waveform) for m in backbones
    ] + [
        (m, None) for m in heads
    ]

    results: list[str] = []
    for model, waveform in all_models:
        delta = _probe_single_model(model, waveform)
        delta_with_headroom = int(delta * 1.1) if delta is not None else None
        value = str(delta_with_headroom) if delta_with_headroom is not None else str(sys.maxsize)
        db.meta.set(f"{_META_PREFIX}{model._path}", value)
        readable = _fmt_bytes(delta_with_headroom) if delta_with_headroom is not None else "unmeasured"
        results.append(f"  {model._path} -> {readable}")

    summary = "\n".join(results)
    logger.info(
        "[vram_probe] Complete — %d measurements (%d backbone(s), %d head(s), %d MB available)\n%s",
        len(all_models),
        n_backbones,
        n_heads,
        available_mb,
        summary,
    )


def has_model_vram_measurements(db: Database) -> bool:
    """Return True if any per-model VRAM measurements exist in meta.

    Args:
        db: Database instance.

    Returns:
        True if at least one ``ml_model_vram:*`` key is present.
    """
    return bool(db.meta.get_by_prefix(_META_PREFIX))


def clear_model_vram_measurements(db: Database) -> None:
    """Delete all per-model VRAM measurements from meta.

    Args:
        db: Database instance.
    """
    existing = db.meta.get_by_prefix(_META_PREFIX)
    for key in existing:
        db.meta.delete(key)
    logger.info("[vram_probe] Cleared %d VRAM measurement(s)", len(existing))


def _make_probe_waveform() -> np.ndarray:
    """Generate a synthetic waveform long enough to fill one full backbone batch.

    ``_BACKBONE_BATCH_SIZE`` is 32 patches.  The worst case is musicnn with
    ``patch_hop=128`` mel frames and ``patch_frames=187``::

        (32 x 128 + 187) x hop_length(256) ~= 1.1 M samples ~= 69 s

    We generate 90 s of 16 kHz white noise to comfortably cover both effnet
    (~50 s) and musicnn (~69 s) without reading a fixture file.

    Returns:
        Float32 array of shape ``(1_440_000,)`` normalised to [-1, 1].
    """
    rng = np.random.default_rng(seed=42)  # deterministic for reproducibility
    return rng.uniform(-1.0, 1.0, size=16000 * 90).astype(np.float32)
