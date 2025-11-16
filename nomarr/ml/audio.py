"""Audio validation and loading for ML processing."""

from __future__ import annotations

import numpy as np
from scipy.signal import resample_poly

from nomarr.ml import backend_essentia

# Use Essentia for audio loading (supports more formats via ffmpeg)
HAVE_ESSENTIA = backend_essentia.is_available()

if HAVE_ESSENTIA:
    MonoLoader = backend_essentia.essentia_tf.standard.MonoLoader
else:
    # Fallback to soundfile if Essentia not available
    import soundfile as sf

    MonoLoader = None


def load_audio_mono(path: str, target_sr: int = 16000) -> tuple[np.ndarray, int, float]:
    """
    Load an audio file as mono float32 in [-1, 1] at target_sr.
    Returns: (y, sr, duration_seconds)

    Uses Essentia's MonoLoader for broad format support (M4A, MP3, FLAC, etc.).
    Falls back to soundfile if Essentia is not available.
    """
    if HAVE_ESSENTIA:
        # Essentia's MonoLoader handles resampling and format conversion automatically
        loader = MonoLoader(filename=path, sampleRate=target_sr, resampleQuality=4)  # type: ignore[misc]
        # Suppress verbose Essentia logs during load

        y = loader()
        y = np.asarray(y, dtype=np.float32)
        sr = int(target_sr)
        duration = float(len(y)) / float(sr) if sr > 0 else 0.0
        return y, sr, duration
    else:
        # Fallback to soundfile (limited format support)
        y, sr = sf.read(path, always_2d=False)
        # Convert to mono
        if hasattr(y, "ndim") and y.ndim == 2:
            y = np.mean(y, axis=1)
        y = np.asarray(y, dtype=np.float32)

        # Resample if needed (polyphase is robust + fast)
        if sr != target_sr:
            # gcd for rational factor
            g = np.gcd(int(sr), int(target_sr))
            up, down = int(target_sr) // g, int(sr) // g
            y = resample_poly(y, up, down).astype(np.float32, copy=False)
            sr = int(target_sr)

        duration = float(len(y)) / float(sr) if sr > 0 else 0.0
        return y, sr, duration


def should_skip_short(duration_s: float, min_duration_s: int, allow_short: bool) -> bool:
    """
    Check if audio file should be skipped due to insufficient duration.

    Args:
        duration_s: Audio duration in seconds
        min_duration_s: Minimum required duration in seconds
        allow_short: If True, allow short files regardless of duration

    Returns:
        True if file should be skipped, False otherwise
    """
    if allow_short:
        return False
    return duration_s < float(min_duration_s)
