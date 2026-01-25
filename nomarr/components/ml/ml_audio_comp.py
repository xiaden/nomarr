"""Audio validation and loading for ML processing."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.signal import resample_poly

from nomarr.components.ml import ml_backend_essentia_comp as backend_essentia
from nomarr.helpers.dto.ml_dto import LoadAudioMonoResult

if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath

# Use Essentia for audio loading (supports more formats via ffmpeg)
HAVE_ESSENTIA = backend_essentia.is_available()

if HAVE_ESSENTIA:
    MonoLoader = backend_essentia.essentia_tf.MonoLoader
else:
    # Fallback to soundfile if Essentia not available
    import soundfile as sf

    MonoLoader = None


def load_audio_mono(path: LibraryPath | str, target_sr: int = 16000) -> LoadAudioMonoResult:
    """
    Load an audio file as mono float32 in [-1, 1] at target_sr.
    Returns: LoadAudioMonoResult with waveform, sample_rate, duration

    Uses Essentia's MonoLoader for broad format support (M4A, MP3, FLAC, etc.).
    Falls back to soundfile if Essentia is not available.

    Args:
        path: LibraryPath (validated) or str (absolute path, validation bypassed)
        target_sr: Target sample rate in Hz

    Raises:
        ValueError: If LibraryPath is invalid
    """
    # Handle both LibraryPath and str
    if isinstance(path, str):
        path_str = path
    else:
        # Enforce validation before file operations for LibraryPath
        if not path.is_valid():
            raise ValueError(f"Cannot load audio from invalid path ({path.status}): {path.absolute} - {path.reason}")
        path_str = str(path.absolute)

    if HAVE_ESSENTIA:
        # Essentia's MonoLoader handles resampling and format conversion automatically
        loader = MonoLoader(filename=path_str, sampleRate=target_sr, resampleQuality=4)  # type: ignore[misc]
        # Suppress verbose Essentia logs during load

        audio = loader()
        audio = np.asarray(audio, dtype=np.float32)
        sr = int(target_sr)
        duration = float(len(audio)) / float(sr) if sr > 0 else 0.0
        return LoadAudioMonoResult(waveform=audio, sample_rate=sr, duration=duration)
    else:
        # Fallback to soundfile (limited format support)
        audio, sr = sf.read(path, always_2d=False)
        # Convert to mono
        if hasattr(audio, "ndim") and audio.ndim == 2:
            audio = np.mean(audio, axis=1)
        audio = np.asarray(audio, dtype=np.float32)

        # Resample if needed (polyphase is robust + fast)
        if sr != target_sr:
            # gcd for rational factor
            gcd = np.gcd(int(sr), int(target_sr))
            up, down = int(target_sr) // gcd, int(sr) // gcd
            audio = resample_poly(audio, up, down).astype(np.float32, copy=False)
            sr = int(target_sr)

        duration = float(len(audio)) / float(sr) if sr > 0 else 0.0
        return LoadAudioMonoResult(waveform=audio, sample_rate=sr, duration=duration)


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
